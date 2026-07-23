"""Tests for fixed-snapshot and claim-level evaluation invariants."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from benchmarks.knowledge_state_search.confirmatory_dataset import build_confirmatory_tasks
from benchmarks.knowledge_state_search.evidence import (
    EvidenceSnapshot,
    SnapshotSource,
    SupportStatus,
)
from benchmarks.knowledge_state_search.ledger import ClaimLevelEvaluator
from benchmarks.knowledge_state_search.models import EvidenceRequirement, SearchTask
from benchmarks.knowledge_state_search.snapshot_audit import audit_snapshot
from benchmarks.knowledge_state_search.snapshot_retriever import SnapshotRetriever


def _source(source_id: str = "s1", task_id: str = "task") -> SnapshotSource:
    source = SnapshotSource(
        source_id=source_id,
        task_id=task_id,
        title="Source title",
        url="https://example.com/source",
        provider="fixture",
        captured_at="2026-07-21",
        text="Evidence text.",
        sha256="",
    )
    return SnapshotSource(**{**source.to_dict(), "sha256": source.compute_sha256()})


def _write_snapshot(root: Path, *, include_query_field: bool = False) -> None:
    source = _source()
    payload = source.to_dict()
    if include_query_field:
        payload["query"] = "leak"
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "snapshot_id": "fixture-v1",
                "schema_version": 1,
                "captured_at": "2026-07-21",
                "task_ids": ["task"],
                "source_count": 1,
                "annotation_count": 1,
            }
        ),
        encoding="utf-8",
    )
    (root / "sources.jsonl").write_text(json.dumps(payload) + "\n", encoding="utf-8")
    (root / "annotations.jsonl").write_text(
        json.dumps(
            {
                "task_id": "task",
                "requirement_id": "core-1",
                "source_id": "s1",
                "status": "supported",
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_source_checksum_is_stable():
    source = _source()

    assert (
        source.sha256
        == hashlib.sha256(
            "\n".join(
                (
                    source.source_id,
                    source.task_id,
                    source.title,
                    source.url,
                    source.provider,
                    source.captured_at,
                    source.text,
                )
            ).encode("utf-8")
        ).hexdigest()
    )


def test_snapshot_rejects_query_leakage(tmp_path: Path):
    _write_snapshot(tmp_path, include_query_field=True)

    with pytest.raises(ValueError, match="planner leakage"):
        EvidenceSnapshot.load(tmp_path)


def test_snapshot_rejects_checksum_mismatch(tmp_path: Path):
    _write_snapshot(tmp_path)
    source_payload = json.loads((tmp_path / "sources.jsonl").read_text(encoding="utf-8"))
    source_payload["text"] = "tampered"
    (tmp_path / "sources.jsonl").write_text(json.dumps(source_payload) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="checksum mismatch"):
        EvidenceSnapshot.load(tmp_path)


def test_claim_evaluator_ignores_query_and_target_labels(tmp_path: Path):
    _write_snapshot(tmp_path)
    snapshot = EvidenceSnapshot.load(tmp_path)
    evaluator = ClaimLevelEvaluator(snapshot)

    metrics = evaluator.evaluate(
        task_id="task",
        requirements=(
            EvidenceRequirement(
                requirement_id="core-1",
                kind="core",
                concept="hidden concept",
                description="hidden claim",
            ),
        ),
        selected_source_ids=("s1",),
    )

    assert metrics.hard_core_recall == 1.0
    assert metrics.learner_recall is None
    assert metrics.evidence_precision == 1.0
    assert metrics.assessments[0].status is SupportStatus.SUPPORTED


def test_empty_learner_set_is_not_success():
    snapshot = EvidenceSnapshot(
        manifest=type(
            "Manifest",
            (),
            {"schema_version": 1, "task_ids": ("task",), "source_count": 0, "annotation_count": 0},
        )(),
        sources=(),
        annotations=(),
    )
    evaluator = ClaimLevelEvaluator(snapshot)

    metrics = evaluator.evaluate(task_id="task", requirements=(), selected_source_ids=())

    assert metrics.learner_recall is None
    assert metrics.hard_core_recall == 0.0


def test_repository_snapshot_v1_loads():
    snapshot = EvidenceSnapshot.load("benchmarks/data/knowledge_state_search_snapshot_v1")

    assert snapshot.manifest.snapshot_id == "knowledge-state-search-v1"
    assert len(snapshot.sources) == 16
    assert len(snapshot.annotations) == 30
    assert set(snapshot.manifest.task_ids) == {
        "kmeans_initialization",
        "overfitting_generalization",
        "pca_covariance",
        "svm_kernel",
    }


def test_snapshot_retriever_is_deterministic_and_annotation_blind():
    snapshot = EvidenceSnapshot.load("benchmarks/data/knowledge_state_search_snapshot_v1")
    retriever = SnapshotRetriever(snapshot)

    first = retriever.search(
        task_id="kmeans_initialization",
        query="KMeans local minima initialization",
        top_k=3,
    )
    second = retriever.search(
        task_id="kmeans_initialization",
        query="KMeans local minima initialization",
        top_k=3,
    )

    assert first == second
    assert len(first) == 3
    assert all(hit.source_id.startswith("kmeans_") for hit in first)
    assert all(not hasattr(hit, "status") for hit in first)


def test_snapshot_retriever_normalizes_kmeans_spelling_and_domain_aliases():
    snapshot = EvidenceSnapshot.load("benchmarks/data/knowledge_state_search_snapshot_v1")
    retriever = SnapshotRetriever(snapshot)

    hits = retriever.search(
        task_id="kmeans_initialization",
        query="K-means objective function iterative update",
        top_k=5,
    )

    lecture_hit = next(hit for hit in hits if hit.source_id == "kmeans_uchicago_lecture")

    assert lecture_hit.score == 0.7


def test_snapshot_retriever_normalizes_alternating_minimization():
    snapshot = EvidenceSnapshot.load("benchmarks/data/knowledge_state_search_snapshot_v1")
    retriever = SnapshotRetriever(snapshot)

    hits = retriever.search(
        task_id="kmeans_initialization",
        query="K-means objective alternating minimization within-cluster sum of squares",
        top_k=5,
    )

    lecture_hit = next(hit for hit in hits if hit.source_id == "kmeans_uchicago_lecture")

    assert lecture_hit.score == 4 / 9 + 0.2
    assert hits[0].source_id == "kmeans_uchicago_lecture"


def test_snapshot_has_supported_core_and_controlled_learner_evidence():
    task_payload = json.loads(Path("benchmarks/data/knowledge_state_search_probe_v1.json").read_text(encoding="utf-8"))
    tasks = tuple(SearchTask.from_dict(item) for item in task_payload["tasks"])
    snapshot = EvidenceSnapshot.load("benchmarks/data/knowledge_state_search_snapshot_v1")

    report = audit_snapshot(tasks, snapshot)

    assert report["summary"]["hard_failure"] is False
    assert report["summary"]["uncovered_requirement_count"] == 0


def test_repository_snapshot_v2_loads_and_exposes_controls():
    snapshot = EvidenceSnapshot.load("benchmarks/data/knowledge_state_search_snapshot_v2")

    assert snapshot.manifest.snapshot_id == "knowledge-state-search-v2"
    assert len(snapshot.sources) == 27
    assert len(snapshot.annotations) == 40
    assert sum(source.provider == "benchmark_negative_control" for source in snapshot.sources) == 4
    assert any(annotation.status is SupportStatus.CONTRADICTED for annotation in snapshot.annotations)


def test_v2_task_builder_adds_multi_gap_profiles():
    payload = json.loads(Path("benchmarks/data/knowledge_state_search_probe_v1.json").read_text(encoding="utf-8"))
    result = build_confirmatory_tasks(payload)

    assert result["schema_version"] == 2
    assert all(any(item["student_id"].endswith("_multi_gap") for item in task["profiles"]) for task in result["tasks"])
    assert len(result["tasks"][0]["profiles"]) == 5


def test_v2_snapshot_audit_covers_all_profile_induced_requirements():
    task_payload = json.loads(Path("benchmarks/data/knowledge_state_search_probe_v2.json").read_text(encoding="utf-8"))
    tasks = tuple(SearchTask.from_dict(item) for item in task_payload["tasks"])
    snapshot = EvidenceSnapshot.load("benchmarks/data/knowledge_state_search_snapshot_v2")

    report = audit_snapshot(tasks, snapshot, all_profiles=True)

    assert report["scope"] == "hard_core_plus_all_task_profiles"
    assert report["summary"]["hard_failure"] is False
    assert report["summary"]["uncovered_requirement_count"] == 0


def test_claim_evaluator_reports_contradiction_and_unannotated_rates():
    snapshot = EvidenceSnapshot.load("benchmarks/data/knowledge_state_search_snapshot_v2")
    evaluator = ClaimLevelEvaluator(snapshot)
    metrics = evaluator.evaluate(
        task_id="kmeans_initialization",
        requirements=(
            EvidenceRequirement(
                requirement_id="core_local_minimum",
                kind="core",
                concept="local minimum",
                description="K-means can stop at a local minimum.",
            ),
        ),
        selected_source_ids=("kmeans_contradiction_global_optimum", "kmeans_distractor_choose_k"),
    )

    assert metrics.contradicted_rate == 0.5
    assert metrics.unannotated_rate == 0.5
    assert metrics.strict_supported_rate == 0.0


def test_claim_evaluator_marks_supported_and_contradicted_claim_as_conflicted():
    snapshot = EvidenceSnapshot.load("benchmarks/data/knowledge_state_search_snapshot_v2")
    evaluator = ClaimLevelEvaluator(snapshot)
    metrics = evaluator.evaluate(
        task_id="kmeans_initialization",
        requirements=(
            EvidenceRequirement(
                requirement_id="core_local_minimum",
                kind="core",
                concept="local minimum",
                description="K-means can stop at a local minimum.",
            ),
        ),
        selected_source_ids=(
            "kmeans_legacy_api",
            "kmeans_contradiction_global_optimum",
        ),
    )

    assert metrics.hard_core_recall == 0.0
    assert metrics.claim_conflict_rate == 1.0
    assert metrics.evidence_precision == 0.5
    assert metrics.assessments[0].conflicted is True
