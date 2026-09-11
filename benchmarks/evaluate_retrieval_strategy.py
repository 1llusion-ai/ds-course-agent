"""Evaluate one query and fusion strategy on a frozen candidate index."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import chromadb
import httpx
from langchain_core.documents import Document
from pydantic import Field

import ds_course_agent.shared.config as config
from benchmarks.adaptive_retrieval_policy import AdaptiveMode, select_adaptive_mode
from benchmarks.build_retrieval_index import create_embedding_client
from benchmarks.retrieval_candidate_schema import CandidateChunk, CandidateChunkBundle, CandidateIndexManifest
from benchmarks.retrieval_evidence_metrics import aggregate_agent_metrics, evidence_at_k, rank_metrics
from benchmarks.retrieval_experiment_schema import AgentQueryMetrics, GroupAggregate
from benchmarks.retrieval_gold_schema import (
    AgentAnnotationBatch,
    Artifact,
    GoldModel,
    QuerySeed,
    QuerySeedDataset,
    Split,
    Text,
)
from benchmarks.retrieval_gold_validation import artifact_bytes
from benchmarks.retrieval_panel_validation import validate_panel_manifest
from benchmarks.retrieval_strategy_schema import (
    RetrievalStrategyMatrix,
    RetrievalStrategyReport,
    RetrievalStrategySpec,
    StrategyQueryResult,
    StrategyRetrievedChunk,
)
from ds_course_agent.retrieval.hybrid_retriever import BM25Retriever, reciprocal_rank_fusion


class RerankResult(GoldModel):
    """One provider rerank score bound to an input document index."""

    index: int = Field(ge=0)
    relevance_score: float
    document: str | None = None


class RerankResponse(GoldModel):
    """Minimal SiliconFlow-compatible rerank response used by the benchmark."""

    id: Text
    results: list[RerankResult]
    meta: dict[str, object] | None = None


def _artifact(root: Path, path: Path) -> Artifact:
    content = path.read_bytes()
    return Artifact(
        path=path.resolve().relative_to(root.resolve()).as_posix(),
        sha256=hashlib.sha256(content).hexdigest(),
    )


def format_embedding_query(query: str, instruction: str | None) -> str:
    """Apply Qwen3's documented instruction/query envelope when requested."""
    if instruction is None:
        return query
    return f"Instruct: {instruction}\nQuery:{query}"


def queries_for_split(queries: QuerySeedDataset, split: Split) -> dict[str, QuerySeed]:
    """Select exactly one frozen split without exposing the other split to evaluation."""
    return {query.id: query for query in queries.queries if query.split == split}


def _rank_lookup(results: list[tuple[int, float]]) -> dict[int, tuple[int, float]]:
    return {doc_idx: (rank, score) for rank, (doc_idx, score) in enumerate(results, start=1)}


def rerank_documents(
    *,
    query: str,
    candidates: list[tuple[int, float]],
    chunks: list[CandidateChunk],
    model: str,
    top_n: int,
) -> list[tuple[int, float]]:
    """Rerank candidate chunk indexes through the configured provider endpoint."""
    if not config.API_KEY:
        raise ValueError("EMBEDDING_API_KEY is required for remote reranking")
    response = httpx.post(
        f"{config.BASE_URL.rstrip('/')}/rerank",
        headers={"Authorization": f"Bearer {config.API_KEY}"},
        json={
            "model": model,
            "query": query,
            "documents": [chunks[doc_idx].content for doc_idx, _ in candidates],
            "top_n": min(top_n, len(candidates)),
            "return_documents": False,
        },
        timeout=max(20.0, float(config.EMBEDDING_TIMEOUT_SECONDS)),
    )
    response.raise_for_status()
    payload = RerankResponse.model_validate(response.json())
    if len(payload.results) != min(top_n, len(candidates)):
        raise ValueError("rerank API returned an unexpected result count")
    ranked = []
    seen = set()
    for item in payload.results:
        if item.index >= len(candidates):
            raise ValueError("rerank API returned an out-of-range document index")
        doc_idx = candidates[item.index][0]
        if doc_idx in seen:
            raise ValueError("rerank API returned a duplicate document index")
        seen.add(doc_idx)
        ranked.append((doc_idx, item.relevance_score))
    return ranked


def evaluate_strategy(
    *,
    root: Path,
    panel_path: Path,
    index_manifest_path: Path,
    output: Path,
    strategy: RetrievalStrategySpec,
    split: Split = "dev",
) -> RetrievalStrategyReport:
    """Run one strategy on the explicitly selected frozen split."""
    root = root.resolve()
    output = output.resolve()
    if not output.is_relative_to(root / "var" / "artifacts" / "kb_eval"):
        raise ValueError("evaluation output must be under var/artifacts/kb_eval")
    if output.exists():
        raise ValueError("evaluation output already exists; refusing overwrite")

    panel = validate_panel_manifest(panel_path, root=root)
    index_manifest = CandidateIndexManifest.model_validate_json(index_manifest_path.read_bytes())
    bundle = CandidateChunkBundle.model_validate_json(artifact_bytes(root, index_manifest.candidate_bundle))
    persist = (root / index_manifest.persist_directory).resolve()
    if not persist.is_relative_to(root / "var" / "chroma_candidates") or persist.is_relative_to(
        root / "var" / "chroma_db"
    ):
        raise ValueError("candidate index path is outside the isolated experiment root")
    collection = chromadb.PersistentClient(path=str(persist)).get_collection(index_manifest.collection_name)
    if collection.count() != index_manifest.document_count:
        raise ValueError("candidate index document count is stale")

    queries = QuerySeedDataset.model_validate_json(artifact_bytes(root, panel.queries))
    query_by_id = queries_for_split(queries, split)
    annotations = []
    for declared in panel.annotations:
        batch = AgentAnnotationBatch.model_validate_json(artifact_bytes(root, declared.artifact))
        annotations.append((declared.annotator_id, {sample.id: sample for sample in batch.samples}))

    chunks = bundle.chunks
    chunk_index_by_id = {chunk.id: index for index, chunk in enumerate(chunks)}
    documents = [Document(page_content=chunk.content, metadata={"chunk_id": chunk.id}) for chunk in chunks]
    bm25 = BM25Retriever()
    bm25.add_documents(documents)

    depths = panel.selection_policy.ranking_depths
    maximum_depth = max(depths)
    ordered_queries = [query_by_id[query_id] for query_id in sorted(query_by_id)]
    decisions = {
        query.id: select_adaptive_mode(query.query, strategy.routing_policy)
        if strategy.retrieval_mode == "adaptive"
        else None
        for query in ordered_queries
    }
    vector_queries = [
        query
        for query in ordered_queries
        if strategy.retrieval_mode != "bm25"
        and (strategy.retrieval_mode != "adaptive" or decisions[query.id].mode is AdaptiveMode.VECTOR)
    ]
    embedded_queries = [format_embedding_query(query.query, strategy.query_instruction) for query in vector_queries]
    embedding_started = time.perf_counter()
    if embedded_queries:
        model = create_embedding_client(index_manifest.embedding)
        query_vectors = model.embed_documents(embedded_queries)
    else:
        query_vectors = []
    query_embedding_seconds = time.perf_counter() - embedding_started
    if len(query_vectors) != len(vector_queries):
        raise ValueError("embedding API returned an unexpected query vector count")
    if any(len(vector) != index_manifest.vector_dimension for vector in query_vectors):
        raise ValueError("query vector dimension differs from candidate index")
    vector_by_id = {query.id: vector for query, vector in zip(vector_queries, query_vectors, strict=True)}

    rows: list[StrategyQueryResult] = []
    for query in ordered_queries:
        embedded_query = format_embedding_query(query.query, strategy.query_instruction)
        bm25_started = time.perf_counter()
        bm25_results = bm25.retrieve(query.query, top_k=strategy.candidate_depth)
        bm25_seconds = time.perf_counter() - bm25_started

        decision = decisions[query.id]
        selected_mode = decision.mode.value if decision is not None else None
        selection_rule = decision.rule if decision is not None else None
        uses_vector = strategy.retrieval_mode not in {"bm25", "adaptive"} or selected_mode == "vector"
        vector_seconds = 0.0
        vector_results = []
        if uses_vector:
            vector_started = time.perf_counter()
            result = collection.query(
                query_embeddings=[vector_by_id[query.id]],
                n_results=min(strategy.candidate_depth, collection.count()),
                include=["distances"],
            )
            vector_seconds = time.perf_counter() - vector_started
            vector_results = [
                (chunk_index_by_id[chunk_id], 1.0 - float(distance))
                for chunk_id, distance in zip(result["ids"][0], result["distances"][0], strict=True)
            ]

        if strategy.retrieval_mode == "bm25" or selected_mode == "bm25":
            ranked_results = bm25_results
        elif strategy.retrieval_mode == "vector" or selected_mode == "vector":
            ranked_results = vector_results
        else:
            ranked_results = reciprocal_rank_fusion(
                [bm25_results, vector_results],
                rank_constant=strategy.rrf_rank_constant or 60,
            )

        rerank_seconds = 0.0
        if strategy.reranker_model is not None:
            rerank_started = time.perf_counter()
            ranked_results = rerank_documents(
                query=query.query,
                candidates=ranked_results[: strategy.candidate_depth],
                chunks=chunks,
                model=strategy.reranker_model,
                top_n=maximum_depth,
            )
            rerank_seconds = time.perf_counter() - rerank_started

        vector_lookup = _rank_lookup(vector_results)
        bm25_lookup = _rank_lookup(bm25_results)
        selected = ranked_results[:maximum_depth]
        ranked_chunks = [chunks[doc_idx] for doc_idx, _ in selected]
        agent_metrics = []
        for annotator_id, samples in annotations:
            sample = samples[query.id]
            if sample.answerability != "answerable":
                continue
            agent_metrics.append(
                AgentQueryMetrics(
                    annotator_id=annotator_id,
                    candidate_has_complete_evidence=evidence_at_k(sample, chunks, len(chunks))["complete_evidence"],
                    retrieval=rank_metrics(sample, ranked_chunks, depths),
                )
            )
        rows.append(
            StrategyQueryResult(
                id=query.id,
                split=split,
                question_type=query.question_type,
                query=query.query,
                embedded_query=embedded_query,
                selected_mode=selected_mode,
                selection_rule=selection_rule,
                vector_search_seconds=vector_seconds,
                bm25_search_seconds=bm25_seconds,
                rerank_seconds=rerank_seconds,
                retrieved=[
                    StrategyRetrievedChunk(
                        rank=rank,
                        chunk_id=chunks[doc_idx].id,
                        ranking_score=float(score),
                        vector_rank=vector_lookup.get(doc_idx, (None, None))[0],
                        vector_similarity=vector_lookup.get(doc_idx, (None, None))[1],
                        bm25_rank=bm25_lookup.get(doc_idx, (None, None))[0],
                        bm25_score=bm25_lookup.get(doc_idx, (None, None))[1],
                    )
                    for rank, (doc_idx, score) in enumerate(selected, start=1)
                ],
                agent_metrics=agent_metrics,
            )
        )

    row_by_id = {row.id: row for row in rows}
    group_reports = []
    for group_name in ("quality_gate", "robustness", "interpretation_sensitive"):
        ids = set(getattr(panel.groups, group_name)) & query_by_id.keys()
        if not ids:
            continue
        agent_grouped: defaultdict[str, list[AgentQueryMetrics]] = defaultdict(list)
        for query_id in ids:
            for metric in row_by_id[query_id].agent_metrics:
                agent_grouped[metric.annotator_id].append(metric)
        group_reports.append(
            GroupAggregate(
                group=group_name,
                agents=[
                    aggregate_agent_metrics(annotator_id, agent_grouped[annotator_id], depths)
                    for annotator_id, _ in annotations
                ],
            )
        )

    report = RetrievalStrategyReport(
        schema_version="retrieval-strategy-experiment/1.0",
        created_at=datetime.now().astimezone(),
        split=split,
        panel=_artifact(root, panel_path),
        candidate_index=_artifact(root, index_manifest_path),
        candidate_id=bundle.candidate.id,
        embedding_id=index_manifest.embedding.id,
        strategy=strategy,
        depths=depths,
        query_embedding_seconds=query_embedding_seconds,
        query_count=len(rows),
        positive_query_count=len(set(panel.groups.robustness) & query_by_id.keys()),
        boundary_query_count=len(set(panel.groups.boundary) & query_by_id.keys()),
        groups=group_reports,
        queries=rows,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    """Resolve one frozen strategy and evaluate an explicitly selected split."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--index-manifest", type=Path, required=True)
    parser.add_argument("--strategy-matrix", type=Path, required=True)
    parser.add_argument("--strategy-id", required=True)
    parser.add_argument("--split", choices=("dev", "test"), default="dev")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    matrix = RetrievalStrategyMatrix.model_validate_json(args.strategy_matrix.read_bytes())
    matches = [strategy for strategy in matrix.strategies if strategy.id == args.strategy_id]
    if len(matches) != 1:
        raise ValueError(f"unknown retrieval strategy: {args.strategy_id}")
    report = evaluate_strategy(
        root=args.root,
        panel_path=args.panel,
        index_manifest_path=args.index_manifest,
        output=args.output,
        strategy=matches[0],
        split=args.split,
    )
    print(json.dumps([group.model_dump(mode="json") for group in report.groups], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
