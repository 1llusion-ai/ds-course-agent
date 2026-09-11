"""Evaluate one isolated candidate index against dual-agent evidence labels."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import chromadb

from benchmarks.build_retrieval_index import create_embedding_client
from benchmarks.retrieval_candidate_schema import CandidateChunkBundle, CandidateIndexManifest
from benchmarks.retrieval_evidence_metrics import aggregate_agent_metrics, evidence_at_k, rank_metrics
from benchmarks.retrieval_experiment_schema import (
    AgentQueryMetrics,
    GroupAggregate,
    QueryExperimentResult,
    RetrievalExperimentReport,
    RetrievedChunk,
)
from benchmarks.retrieval_gold_schema import AgentAnnotationBatch, Artifact, QuerySeedDataset
from benchmarks.retrieval_gold_validation import artifact_bytes
from benchmarks.retrieval_panel_validation import validate_panel_manifest


def _artifact(root: Path, path: Path) -> Artifact:
    content = path.read_bytes()
    return Artifact(
        path=path.resolve().relative_to(root.resolve()).as_posix(),
        sha256=hashlib.sha256(content).hexdigest(),
    )


def evaluate_candidate(
    *,
    root: Path,
    panel_path: Path,
    index_manifest_path: Path,
    output: Path,
    split: str,
) -> RetrievalExperimentReport:
    """Run a fixed-depth vector evaluation and write a fresh report under var/artifacts."""
    root = root.resolve()
    output = output.resolve()
    if split not in {"dev", "test"}:
        raise ValueError("split must be dev or test")
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
    query_by_id = {query.id: query for query in queries.queries if query.split == split}
    annotations = []
    for declared in panel.annotations:
        batch = AgentAnnotationBatch.model_validate_json(artifact_bytes(root, declared.artifact))
        annotations.append((declared.annotator_id, {sample.id: sample for sample in batch.samples}))
    chunk_by_id = {chunk.id: chunk for chunk in bundle.chunks}
    depths = panel.selection_policy.ranking_depths
    maximum_depth = max(depths)
    model = create_embedding_client(index_manifest.embedding)
    rows: list[QueryExperimentResult] = []
    boundary_ids = set(panel.groups.boundary)
    ordered_queries = [query_by_id[query_id] for query_id in sorted(query_by_id)]
    embedding_started = time.perf_counter()
    query_vectors = model.embed_documents(
        [index_manifest.embedding.query_prefix + query.query for query in ordered_queries]
    )
    query_embedding_seconds = time.perf_counter() - embedding_started
    if len(query_vectors) != len(ordered_queries):
        raise ValueError("embedding API returned an unexpected query vector count")
    if any(len(vector) != index_manifest.vector_dimension for vector in query_vectors):
        raise ValueError("query vector dimension differs from candidate index")
    for query, vector in zip(ordered_queries, query_vectors, strict=True):
        query_id = query.id
        started = time.perf_counter()
        result = collection.query(
            query_embeddings=[vector],
            n_results=min(maximum_depth, collection.count()),
            include=["distances"],
        )
        elapsed = time.perf_counter() - started
        retrieved_ids = result["ids"][0]
        distances = result["distances"][0]
        ranked = [chunk_by_id[chunk_id] for chunk_id in retrieved_ids]
        agent_metrics = []
        for annotator_id, samples in annotations:
            sample = samples[query_id]
            if sample.answerability != "answerable":
                continue
            retrieval_metrics = rank_metrics(sample, ranked, depths)
            agent_metrics.append(
                AgentQueryMetrics(
                    annotator_id=annotator_id,
                    candidate_has_complete_evidence=evidence_at_k(sample, bundle.chunks, len(bundle.chunks))[
                        "complete_evidence"
                    ],
                    retrieval=retrieval_metrics,
                )
            )
        rows.append(
            QueryExperimentResult(
                id=query_id,
                split=query.split,
                question_type=query.question_type,
                query=query.query,
                vector_search_seconds=elapsed,
                retrieved=[
                    RetrievedChunk(rank=rank, chunk_id=chunk_id, distance=float(distance))
                    for rank, (chunk_id, distance) in enumerate(zip(retrieved_ids, distances, strict=True), start=1)
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
    report = RetrievalExperimentReport(
        schema_version="retrieval-evidence-experiment/1.0",
        created_at=datetime.now().astimezone(),
        split=split,
        panel=_artifact(root, panel_path),
        candidate_index=_artifact(root, index_manifest_path),
        candidate_id=bundle.candidate.id,
        embedding_id=index_manifest.embedding.id,
        depths=depths,
        query_embedding_seconds=query_embedding_seconds,
        query_count=len(rows),
        positive_query_count=len(set(panel.groups.robustness) & query_by_id.keys()),
        boundary_query_count=len(boundary_ids & query_by_id.keys()),
        groups=group_reports,
        queries=rows,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    """Evaluate one candidate index while keeping dev and test outputs separate."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--index-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--split", choices=("dev", "test"), default="dev")
    args = parser.parse_args()
    report = evaluate_candidate(
        root=args.root,
        panel_path=args.panel,
        index_manifest_path=args.index_manifest,
        output=args.output,
        split=args.split,
    )
    print(json.dumps([group.model_dump(mode="json") for group in report.groups], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
