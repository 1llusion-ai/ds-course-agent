"""Evaluate token-bounded context assembly over a frozen retrieval ranking."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import chromadb
import numpy as np
import tiktoken

from benchmarks.retrieval_candidate_schema import CandidateChunk, CandidateChunkBundle, CandidateIndexManifest
from benchmarks.retrieval_context_schema import (
    ContextAgentAggregate,
    ContextAgentMetrics,
    ContextAssemblyResult,
    ContextEvidenceMetrics,
    ContextGroupAggregate,
    ContextQueryResult,
    ContextSelectedChunk,
    ContextSourceSpan,
    ContextStrategyMatrix,
    ContextStrategySpec,
    RetrievalContextReport,
)
from benchmarks.retrieval_evidence_metrics import (
    IntervalMap,
    evidence_for_intervals,
    interval_length,
    merge_ranges,
)
from benchmarks.retrieval_gold_schema import (
    AgentAnnotationBatch,
    Artifact,
    QuerySeedDataset,
    Sample,
    SourceManifest,
    SourcePage,
)
from benchmarks.retrieval_gold_validation import artifact_bytes
from benchmarks.retrieval_panel_validation import validate_panel_manifest
from benchmarks.retrieval_strategy_schema import RetrievalStrategyReport, StrategyRetrievedChunk


@dataclass(frozen=True)
class MmrDecision:
    """One MMR-selected chunk and the scores that caused its selection."""

    chunk_id: str
    redundancy_similarity: float
    selection_score: float


@dataclass(frozen=True)
class OrderedCandidate:
    """A retrieved chunk in the order considered for context assembly."""

    retrieved: StrategyRetrievedChunk
    chunk: CandidateChunk
    redundancy_similarity: float | None
    selection_score: float | None


def _artifact(root: Path, path: Path) -> Artifact:
    content = path.read_bytes()
    return Artifact(
        path=path.resolve().relative_to(root.resolve()).as_posix(),
        sha256=hashlib.sha256(content).hexdigest(),
    )


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def load_tokenizer(root: Path, name: str) -> tiktoken.Encoding:
    """Load a tokenizer from the project runtime cache after its one-time seed."""
    os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(root.resolve() / "var" / "cache" / "tiktoken"))
    return tiktoken.get_encoding(name)


def subtract_interval(interval: tuple[int, int], covered: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Subtract merged half-open intervals from one half-open source interval."""
    start, end = interval
    if end <= start:
        raise ValueError("source interval end must exceed start")
    remaining: list[tuple[int, int]] = []
    cursor = start
    for covered_start, covered_end in merge_ranges(covered):
        if covered_end <= cursor:
            continue
        if covered_start >= end:
            break
        if covered_start > cursor:
            remaining.append((cursor, min(covered_start, end)))
        cursor = max(cursor, covered_end)
        if cursor >= end:
            break
    if cursor < end:
        remaining.append((cursor, end))
    return remaining


def mmr_order(
    chunk_ids: list[str],
    relevance_scores: dict[str, float],
    embeddings: dict[str, list[float]],
    lambda_mult: float,
) -> list[MmrDecision]:
    """Order candidates by retrieval relevance minus selected-chunk redundancy."""
    if not 0.0 <= lambda_mult <= 1.0:
        raise ValueError("MMR lambda must be between zero and one")
    if len(chunk_ids) != len(set(chunk_ids)):
        raise ValueError("MMR candidate IDs must be unique")
    if set(chunk_ids) != relevance_scores.keys() or set(chunk_ids) != embeddings.keys():
        raise ValueError("MMR scores and embeddings must match candidate IDs")

    matrix = np.asarray([embeddings[chunk_id] for chunk_id in chunk_ids], dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[1] == 0:
        raise ValueError("MMR embeddings must form a non-empty matrix")
    norms = np.linalg.norm(matrix, axis=1)
    if np.any(norms == 0.0):
        raise ValueError("MMR embeddings must be non-zero")
    normalized = matrix / norms[:, None]
    index_by_id = {chunk_id: index for index, chunk_id in enumerate(chunk_ids)}
    rank_by_id = {chunk_id: rank for rank, chunk_id in enumerate(chunk_ids)}

    selected: list[str] = []
    decisions: list[MmrDecision] = []
    remaining = set(chunk_ids)
    while remaining:
        scored: list[tuple[float, float, int, str]] = []
        diagnostics: dict[str, tuple[float, float]] = {}
        for chunk_id in remaining:
            if selected:
                candidate_vector = normalized[index_by_id[chunk_id]]
                redundancy = max(
                    float(candidate_vector @ normalized[index_by_id[selected_id]]) for selected_id in selected
                )
            else:
                redundancy = 0.0
            score = lambda_mult * relevance_scores[chunk_id] - (1.0 - lambda_mult) * redundancy
            diagnostics[chunk_id] = (redundancy, score)
            scored.append((score, relevance_scores[chunk_id], -rank_by_id[chunk_id], chunk_id))
        chosen = max(scored)[3]
        redundancy, score = diagnostics[chosen]
        decisions.append(
            MmrDecision(
                chunk_id=chosen,
                redundancy_similarity=redundancy,
                selection_score=score,
            )
        )
        selected.append(chosen)
        remaining.remove(chosen)
    return decisions


def _ordered_candidates(
    retrieved: list[StrategyRetrievedChunk],
    chunk_by_id: dict[str, CandidateChunk],
    strategy: ContextStrategySpec,
    embeddings: dict[str, list[float]],
) -> list[OrderedCandidate]:
    if strategy.selection_mode != "mmr_source_dedup":
        return [
            OrderedCandidate(
                retrieved=item,
                chunk=chunk_by_id[item.chunk_id],
                redundancy_similarity=None,
                selection_score=None,
            )
            for item in retrieved
        ]

    chunk_ids = [item.chunk_id for item in retrieved]
    retrieved_by_id = {item.chunk_id: item for item in retrieved}
    decisions = mmr_order(
        chunk_ids,
        {item.chunk_id: item.ranking_score for item in retrieved},
        {chunk_id: embeddings[chunk_id] for chunk_id in chunk_ids},
        strategy.mmr_lambda if strategy.mmr_lambda is not None else 0.0,
    )
    return [
        OrderedCandidate(
            retrieved=retrieved_by_id[decision.chunk_id],
            chunk=chunk_by_id[decision.chunk_id],
            redundancy_similarity=decision.redundancy_similarity,
            selection_score=decision.selection_score,
        )
        for decision in decisions
    ]


def _chunk_spans(
    chunk: CandidateChunk,
    *,
    covered: IntervalMap,
    deduplicate: bool,
) -> list[ContextSourceSpan]:
    key = (chunk.source_id, chunk.source_page)
    intervals = [(chunk.source_start, chunk.source_end)]
    if deduplicate:
        intervals = subtract_interval(intervals[0], covered.get(key, []))
    return [
        ContextSourceSpan(
            source_id=chunk.source_id,
            source_page=chunk.source_page,
            book_page=chunk.book_page,
            start=start,
            end=end,
        )
        for start, end in intervals
        if end > start
    ]


def _format_block(
    selection_rank: int,
    spans: list[ContextSourceSpan],
    source_text: dict[tuple[str, int], str],
) -> str:
    page = spans[0].book_page
    pieces = [source_text[(span.source_id, span.source_page)][span.start : span.end].strip() for span in spans]
    content = "\n[...]\n".join(piece for piece in pieces if piece)
    return f"[片段 {selection_rank} | 教材第{page}页]\n{content}\n\n"


def _spans_to_intervals(spans: list[ContextSourceSpan]) -> IntervalMap:
    grouped: defaultdict[tuple[str, int], list[tuple[int, int]]] = defaultdict(list)
    for span in spans:
        grouped[(span.source_id, span.source_page)].append((span.start, span.end))
    return {key: merge_ranges(ranges) for key, ranges in grouped.items()}


def assemble_context(
    *,
    ordered: list[OrderedCandidate],
    strategy: ContextStrategySpec,
    token_budget: int,
    source_text: dict[tuple[str, int], str],
    tokenizer: tiktoken.Encoding,
    annotations: list[tuple[str, Sample]],
) -> ContextAssemblyResult:
    """Assemble one context while retaining exact included source intervals."""
    deduplicate = strategy.selection_mode in {"source_overlap_dedup", "mmr_source_dedup"}
    covered: IntervalMap = {}
    selected: list[ContextSelectedChunk] = []
    selected_spans: list[ContextSourceSpan] = []
    blocks: list[str] = []
    skipped_fully_covered = 0
    stopped_on_overflow = False
    used_tokens = 0
    pre_dedup_source_characters = 0

    for candidate in ordered:
        spans = _chunk_spans(candidate.chunk, covered=covered, deduplicate=deduplicate)
        if not spans:
            skipped_fully_covered += 1
            continue
        block = _format_block(len(selected) + 1, spans, source_text)
        if not block.strip():
            skipped_fully_covered += 1
            continue
        candidate_context = "".join([*blocks, block])
        candidate_tokens = len(tokenizer.encode(candidate_context, disallowed_special=()))
        if candidate_tokens > token_budget:
            stopped_on_overflow = True
            break

        source_characters = sum(span.end - span.start for span in spans)
        pre_dedup_source_characters += candidate.chunk.source_end - candidate.chunk.source_start
        selected.append(
            ContextSelectedChunk(
                selection_rank=len(selected) + 1,
                retrieval_rank=candidate.retrieved.rank,
                chunk_id=candidate.chunk.id,
                retrieval_score=candidate.retrieved.ranking_score,
                redundancy_similarity=candidate.redundancy_similarity,
                selection_score=candidate.selection_score,
                source_spans=spans,
                source_characters=source_characters,
                context_tokens=candidate_tokens - used_tokens,
            )
        )
        blocks.append(block)
        selected_spans.extend(spans)
        used_tokens = candidate_tokens
        if deduplicate:
            for key, ranges in _spans_to_intervals(spans).items():
                covered[key] = merge_ranges([*covered.get(key, []), *ranges])

    context = "".join(blocks).rstrip()
    included_source_characters = sum(item.source_characters for item in selected)
    selected_intervals = _spans_to_intervals(selected_spans)
    unique_source_characters = interval_length(selected_intervals)
    agent_metrics = [
        ContextAgentMetrics(
            annotator_id=annotator_id,
            evidence=ContextEvidenceMetrics.model_validate(
                {
                    key: value
                    for key, value in evidence_for_intervals(sample, selected_intervals).items()
                    if key != "sufficient_hit"
                }
            ),
        )
        for annotator_id, sample in annotations
        if sample.answerability == "answerable"
    ]
    return ContextAssemblyResult(
        strategy_id=strategy.id,
        token_budget=token_budget,
        used_tokens=used_tokens,
        context_characters=len(context),
        context_sha256=hashlib.sha256(context.encode("utf-8")).hexdigest(),
        selected_chunk_count=len(selected),
        skipped_fully_covered_count=skipped_fully_covered,
        stopped_on_overflow=stopped_on_overflow,
        pre_dedup_source_characters=pre_dedup_source_characters,
        included_source_characters=included_source_characters,
        unique_source_characters=unique_source_characters,
        duplicate_source_characters=included_source_characters - unique_source_characters,
        dedup_removed_source_characters=pre_dedup_source_characters - included_source_characters,
        selected=selected,
        agent_metrics=agent_metrics,
    )


def _load_embeddings(
    *,
    root: Path,
    manifest: CandidateIndexManifest,
    chunk_ids: list[str],
) -> dict[str, list[float]]:
    persist = (root / manifest.persist_directory).resolve()
    if not persist.is_relative_to(root / "var" / "chroma_candidates") or persist.is_relative_to(
        root / "var" / "chroma_db"
    ):
        raise ValueError("candidate index path is outside the isolated experiment root")
    collection = chromadb.PersistentClient(path=str(persist)).get_collection(manifest.collection_name)
    if collection.count() != manifest.document_count:
        raise ValueError("candidate index document count is stale")
    result = collection.get(ids=chunk_ids, include=["embeddings"])
    returned = result.get("embeddings")
    if returned is None or len(result["ids"]) != len(chunk_ids):
        raise ValueError("candidate index did not return every requested embedding")
    embeddings = {chunk_id: list(map(float, vector)) for chunk_id, vector in zip(result["ids"], returned, strict=True)}
    if set(embeddings) != set(chunk_ids):
        raise ValueError("candidate index returned unexpected embedding IDs")
    if any(len(vector) != manifest.vector_dimension for vector in embeddings.values()):
        raise ValueError("candidate index returned an unexpected vector dimension")
    return embeddings


def _aggregate_groups(
    *,
    panel,
    rows: list[ContextQueryResult],
    strategies: list[ContextStrategySpec],
    budgets: list[int],
    annotator_ids: list[str],
) -> list[ContextGroupAggregate]:
    row_by_id = {row.id: row for row in rows}
    groups: list[ContextGroupAggregate] = []
    for group_name in ("quality_gate", "robustness", "interpretation_sensitive"):
        query_ids = [query_id for query_id in getattr(panel.groups, group_name) if query_id in row_by_id]
        if not query_ids:
            continue
        for strategy in strategies:
            for budget in budgets:
                assemblies = [
                    next(
                        assembly
                        for assembly in row_by_id[query_id].assemblies
                        if assembly.strategy_id == strategy.id and assembly.token_budget == budget
                    )
                    for query_id in query_ids
                ]
                agents = []
                for annotator_id in annotator_ids:
                    paired = [
                        (
                            assembly,
                            next(metric for metric in assembly.agent_metrics if metric.annotator_id == annotator_id),
                        )
                        for assembly in assemblies
                    ]
                    agents.append(
                        ContextAgentAggregate(
                            annotator_id=annotator_id,
                            sample_count=len(paired),
                            evidence_coverage=_mean([pair[1].evidence.evidence_coverage for pair in paired]),
                            region_recall=_mean([pair[1].evidence.region_recall for pair in paired]),
                            complete_evidence_rate=_mean(
                                [float(pair[1].evidence.complete_evidence) for pair in paired]
                            ),
                            mean_used_tokens=_mean([float(pair[0].used_tokens) for pair in paired]),
                            mean_selected_chunks=_mean([float(pair[0].selected_chunk_count) for pair in paired]),
                            mean_budget_utilization=_mean(
                                [pair[0].used_tokens / pair[0].token_budget for pair in paired]
                            ),
                            mean_duplicate_source_rate=_mean(
                                [
                                    pair[0].duplicate_source_characters / pair[0].included_source_characters
                                    if pair[0].included_source_characters
                                    else 0.0
                                    for pair in paired
                                ]
                            ),
                            mean_dedup_removed_rate=_mean(
                                [
                                    pair[0].dedup_removed_source_characters / pair[0].pre_dedup_source_characters
                                    if pair[0].pre_dedup_source_characters
                                    else 0.0
                                    for pair in paired
                                ]
                            ),
                        )
                    )
                groups.append(
                    ContextGroupAggregate(
                        group=group_name,
                        strategy_id=strategy.id,
                        token_budget=budget,
                        agents=agents,
                    )
                )
    return groups


def evaluate_context(
    *,
    root: Path,
    panel_path: Path,
    index_manifest_path: Path,
    retrieval_report_path: Path,
    strategy_matrix_path: Path,
    output: Path,
    now: datetime | None = None,
) -> RetrievalContextReport:
    """Evaluate frozen context strategies without issuing new embedding requests."""
    root = root.resolve()
    output = output.resolve()
    if not output.is_relative_to(root / "var" / "artifacts" / "kb_eval"):
        raise ValueError("context evaluation output must be under var/artifacts/kb_eval")
    if output.exists():
        raise ValueError("context evaluation output already exists; refusing overwrite")

    panel = validate_panel_manifest(panel_path, root=root)
    index_manifest = CandidateIndexManifest.model_validate_json(index_manifest_path.read_bytes())
    retrieval_report = RetrievalStrategyReport.model_validate_json(retrieval_report_path.read_bytes())
    matrix = ContextStrategyMatrix.model_validate_json(strategy_matrix_path.read_bytes())
    if retrieval_report.strategy.retrieval_mode != "vector" or any(
        (
            retrieval_report.strategy.query_instruction is not None,
            retrieval_report.strategy.reranker_model is not None,
            retrieval_report.strategy.routing_policy is not None,
        )
    ):
        raise ValueError("context evaluation requires a raw vector retrieval report")
    artifact_bytes(root, retrieval_report.panel)
    if retrieval_report.candidate_index != _artifact(root, index_manifest_path):
        raise ValueError("retrieval report was not produced from the selected candidate index")

    queries = QuerySeedDataset.model_validate_json(artifact_bytes(root, panel.queries))
    expected_queries = {query.id: query for query in queries.queries if query.split == retrieval_report.split}
    if set(expected_queries) != {query.id for query in retrieval_report.queries}:
        raise ValueError("retrieval report query IDs differ from the selected panel split")
    for query in retrieval_report.queries:
        expected = expected_queries[query.id]
        if query.query != expected.query or query.question_type != expected.question_type:
            raise ValueError(f"retrieval report query changed since ranking: {query.id}")

    bundle = CandidateChunkBundle.model_validate_json(artifact_bytes(root, index_manifest.candidate_bundle))
    chunk_by_id = {chunk.id: chunk for chunk in bundle.chunks}
    if retrieval_report.candidate_id != bundle.candidate.id:
        raise ValueError("retrieval report candidate differs from candidate bundle")
    if retrieval_report.embedding_id != index_manifest.embedding.id:
        raise ValueError("retrieval report embedding differs from candidate index")
    if any(len(query.retrieved) != matrix.candidate_depth for query in retrieval_report.queries):
        raise ValueError("retrieval report does not contain the frozen candidate depth")

    source_manifest = SourceManifest.model_validate_json(artifact_bytes(root, panel.source_manifest))
    pages = [
        SourcePage.model_validate_json(line)
        for line in artifact_bytes(root, source_manifest.pages_export).decode("utf-8").splitlines()
    ]
    source_text = {(page.source_id, page.source_page): page.text for page in pages}
    annotations = []
    for declared in panel.annotations:
        batch = AgentAnnotationBatch.model_validate_json(artifact_bytes(root, declared.artifact))
        annotations.append((declared.annotator_id, {sample.id: sample for sample in batch.samples}))

    retrieved_chunk_ids = list(
        dict.fromkeys(item.chunk_id for query in retrieval_report.queries for item in query.retrieved)
    )
    missing_chunks = set(retrieved_chunk_ids) - chunk_by_id.keys()
    if missing_chunks:
        raise ValueError(f"retrieval report references unknown chunks: {sorted(missing_chunks)}")
    embeddings = (
        _load_embeddings(
            root=root,
            manifest=index_manifest,
            chunk_ids=retrieved_chunk_ids,
        )
        if any(strategy.selection_mode == "mmr_source_dedup" for strategy in matrix.strategies)
        else {}
    )
    tokenizer = load_tokenizer(root, matrix.tokenizer)
    budgets = panel.selection_policy.context_token_budgets
    rows = []
    for query in retrieval_report.queries:
        sample_annotations = [(annotator_id, samples[query.id]) for annotator_id, samples in annotations]
        assemblies = []
        for strategy in matrix.strategies:
            ordered = _ordered_candidates(query.retrieved, chunk_by_id, strategy, embeddings)
            for budget in budgets:
                assemblies.append(
                    assemble_context(
                        ordered=ordered,
                        strategy=strategy,
                        token_budget=budget,
                        source_text=source_text,
                        tokenizer=tokenizer,
                        annotations=sample_annotations,
                    )
                )
        rows.append(
            ContextQueryResult(
                id=query.id,
                split=retrieval_report.split,
                question_type=query.question_type,
                query=query.query,
                assemblies=assemblies,
            )
        )

    groups = _aggregate_groups(
        panel=panel,
        rows=rows,
        strategies=matrix.strategies,
        budgets=budgets,
        annotator_ids=[annotator_id for annotator_id, _ in annotations],
    )
    report = RetrievalContextReport(
        schema_version="retrieval-context-experiment/1.0",
        created_at=now or datetime.now().astimezone(),
        split=retrieval_report.split,
        panel=_artifact(root, panel_path),
        candidate_index=_artifact(root, index_manifest_path),
        retrieval_report=_artifact(root, retrieval_report_path),
        strategy_matrix=_artifact(root, strategy_matrix_path),
        candidate_id=bundle.candidate.id,
        embedding_id=index_manifest.embedding.id,
        tokenizer=matrix.tokenizer,
        candidate_depth=matrix.candidate_depth,
        token_budgets=budgets,
        strategies=matrix.strategies,
        query_count=len(rows),
        groups=groups,
        queries=rows,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    """Evaluate one split's frozen retrieval ranking under a context matrix."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--index-manifest", type=Path, required=True)
    parser.add_argument("--retrieval-report", type=Path, required=True)
    parser.add_argument("--strategy-matrix", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    report = evaluate_context(
        root=args.root,
        panel_path=args.panel,
        index_manifest_path=args.index_manifest,
        retrieval_report_path=args.retrieval_report,
        strategy_matrix_path=args.strategy_matrix,
        output=args.output,
    )
    print(json.dumps([group.model_dump(mode="json") for group in report.groups], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
