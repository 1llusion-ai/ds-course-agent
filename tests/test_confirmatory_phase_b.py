"""Tests for the frozen Phase B confirmatory-data contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from benchmarks.knowledge_state_search.confirmatory_schema import (
    ConfirmatorySchema,
    file_sha256,
)
from benchmarks.knowledge_state_search.phase_b_freeze import (
    build_phase_b_freeze_report,
    run_phase_b_freeze_check,
)

_DATA_FILES = (
    "tasks.jsonl",
    "profiles.jsonl",
    "claims.jsonl",
    "claim_edges.jsonl",
    "sources.jsonl",
    "evidence_annotations.jsonl",
    "splits.json",
    "annotation_audit.json",
)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def _source(payload: dict[str, str]) -> dict[str, str]:
    raw = "\n".join(
        payload[field]
        for field in (
            "source_id",
            "task_id",
            "title",
            "url",
            "provider",
            "captured_at",
            "text",
        )
    )
    return {**payload, "sha256": hashlib.sha256(raw.encode()).hexdigest()}


def _write_phase_b_fixture(root: Path) -> None:
    tasks: list[dict[str, object]] = []
    profiles: list[dict[str, object]] = []
    claims: list[dict[str, object]] = []
    edges: list[dict[str, object]] = []
    sources: list[dict[str, object]] = []
    annotations: list[dict[str, object]] = []
    dev_task_ids = []
    test_task_ids = []

    relation_by_source_index = (
        *(["supported"] * 5),
        *(["partial"] * 2),
        "contradicted",
        *(["distractor"] * 3),
        "unrelated",
    )
    kinds = ("prerequisite",) * 4 + ("misconception",) * 4 + ("goal",) * 4
    field_by_kind = {
        "prerequisite": "weak_concept",
        "misconception": "misconception",
        "goal": "learning_goal",
    }

    for task_index, kind in enumerate(kinds, 1):
        prefix = f"pb_t{task_index:02d}"
        tasks.append(
            {
                "task_id": prefix,
                "question": f"Phase B teaching question {task_index}?",
                "target_concepts": [f"topic_{task_index}"],
            }
        )
        trigger = f"trigger_{task_index}"
        no_gap = {
            "task_id": prefix,
            "profile_id": f"{prefix}_profile_00",
            "level": "intermediate",
            "mastered_concepts": [trigger] if kind == "prerequisite" else [],
            "weak_concepts": [],
            "misconceptions": [],
            "learning_goal": f"baseline_objective_{task_index}",
        }
        single_gap = {
            **no_gap,
            "profile_id": f"{prefix}_profile_01",
            "mastered_concepts": [],
        }
        if kind == "prerequisite":
            single_gap["weak_concepts"] = [trigger]
        elif kind == "misconception":
            single_gap["misconceptions"] = [trigger]
        else:
            single_gap["learning_goal"] = trigger
        profiles.extend((no_gap, single_gap))

        for claim_index in range(1, 6):
            claims.append(
                {
                    "task_id": prefix,
                    "claim_id": f"{prefix}_c{claim_index:02d}",
                    "kind": "core",
                    "concept": f"core_concept_{task_index}_{claim_index}",
                    "description": f"Core claim {claim_index} for task {task_index}.",
                    "hard": True,
                    "priority": 3,
                    "oracle_query": f"core evidence query {task_index} {claim_index}",
                    "profile_condition": None,
                }
            )
        learner_claim_id = f"{prefix}_c06"
        claims.append(
            {
                "task_id": prefix,
                "claim_id": learner_claim_id,
                "kind": kind,
                "concept": f"learner_concept_{task_index}",
                "description": f"Learner claim for task {task_index}.",
                "hard": False,
                "priority": 2,
                "oracle_query": f"learner evidence query {task_index}",
                "profile_condition": {
                    "field": field_by_kind[kind],
                    "value": trigger,
                },
            }
        )

        edge_rows = (
            (1, learner_claim_id, f"{prefix}_c01", "prerequisite", f"{prefix}_p01"),
            (2, f"{prefix}_c01", f"{prefix}_c02", "causal", f"{prefix}_p01"),
            (3, learner_claim_id, f"{prefix}_c03", "explains", f"{prefix}_p02"),
            (4, f"{prefix}_c03", f"{prefix}_c04", "qualifies", f"{prefix}_p02"),
        )
        for edge_index, from_claim, to_claim, edge_type, path_id in edge_rows:
            edges.append(
                {
                    "task_id": prefix,
                    "edge_id": f"{prefix}_e{edge_index:02d}",
                    "from_claim_id": from_claim,
                    "to_claim_id": to_claim,
                    "edge_type": edge_type,
                    "required": True,
                    "path_ids": [path_id],
                }
            )

        target_ids = [
            *(("claim", f"{prefix}_c{claim_index:02d}") for claim_index in range(1, 7)),
            *(("edge", f"{prefix}_e{edge_index:02d}") for edge_index in range(1, 5)),
        ]
        for source_index, relation in enumerate(relation_by_source_index, 1):
            source_id = f"{prefix}_s{source_index:02d}"
            sources.append(
                _source(
                    {
                        "source_id": source_id,
                        "task_id": prefix,
                        "title": f"Natural source {task_index}-{source_index}",
                        "url": f"https://source-{task_index}-{source_index}.edu/resource",
                        "provider": f"source-{task_index}-{source_index}.edu",
                        "captured_at": "2026-07-22T00:00:00+00:00",
                        "text": (
                            "This is a verbatim unit-test excerpt representing a sufficiently long natural source. "
                            "It contains stable prose for checksum and Phase B source-contract validation. "
                        ).strip()
                        * 2,
                    }
                )
            )
            annotations.extend(
                {
                    "task_id": prefix,
                    "target_type": target_type,
                    "target_id": target_id,
                    "source_id": source_id,
                    "relation": relation,
                }
                for target_type, target_id in target_ids
            )

        if task_index in {1, 5, 9}:
            dev_task_ids.append(prefix)
        else:
            test_task_ids.append(prefix)

    _write_jsonl(root / "tasks.jsonl", tasks)
    _write_jsonl(root / "profiles.jsonl", profiles)
    _write_jsonl(root / "claims.jsonl", claims)
    _write_jsonl(root / "claim_edges.jsonl", edges)
    _write_jsonl(root / "sources.jsonl", sources)
    _write_jsonl(root / "evidence_annotations.jsonl", annotations)
    (root / "splits.json").write_text(
        json.dumps(
            {
                "splits": {
                    "phase_b_dev": dev_task_ids,
                    "phase_b_test": test_task_ids,
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "annotation_audit.json").write_text(
        json.dumps(
            {
                "status": "dual_human_adjudicated",
                "annotators": ["annotator_a", "annotator_b", "adjudicator_c"],
                "adjudicated": True,
                "independently_judged_pairs": len(annotations),
                "notes": "Phase B contract fixture.",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = {
        "benchmark_id": "phase-b-fixture",
        "schema_version": 3,
        "created_at": "2026-07-22T00:00:00+00:00",
        "source_capture_method": "Verbatim excerpts captured from natural public web pages.",
        "provenance_note": "Dual-annotated and adjudicated Phase B contract fixture.",
        "task_ids": [task["task_id"] for task in tasks],
        "counts": {
            "tasks": len(tasks),
            "profiles": len(profiles),
            "claims": len(claims),
            "edges": len(edges),
            "sources": len(sources),
            "annotations": len(annotations),
        },
        "file_sha256": {filename: file_sha256(root / filename) for filename in _DATA_FILES},
    }
    (root / "manifest.json").write_text(json.dumps(manifest) + "\n", encoding="utf-8")


def _rehash_manifest(root: Path, filename: str) -> None:
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["file_sha256"][filename] = file_sha256(root / filename)
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")


def test_phase_b_contract_accepts_frozen_balanced_dataset(tmp_path):
    _write_phase_b_fixture(tmp_path)

    schema = ConfirmatorySchema.load(tmp_path)
    schema.validate_phase_b_contract()

    assert len(schema.tasks) == 12
    assert len(schema.annotations) == 1440


def test_phase_b_freeze_report_keeps_method_runs_blocked(tmp_path):
    _write_phase_b_fixture(tmp_path)

    report = build_phase_b_freeze_report(ConfirmatorySchema.load(tmp_path))

    assert report["status"] == "pass"
    assert report["counts"]["required_paths"] == 24
    assert report["learner_gap_types"] == {
        "goal": 4,
        "misconception": 4,
        "prerequisite": 4,
    }
    assert report["method_runs_authorized"] is False
    assert report["next_gate"] == "deterministic_gold_vs_core_discriminability"


def test_phase_b_freeze_check_reports_missing_dataset(tmp_path):
    report = run_phase_b_freeze_check(tmp_path / "missing")

    assert report["status"] == "fail"
    assert report["method_runs_authorized"] is False


def test_phase_b_contract_requires_independent_adjudication(tmp_path):
    _write_phase_b_fixture(tmp_path)
    audit_path = tmp_path / "annotation_audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    audit["adjudicated"] = False
    audit["independently_judged_pairs"] = 0
    audit_path.write_text(json.dumps(audit) + "\n", encoding="utf-8")
    _rehash_manifest(tmp_path, "annotation_audit.json")

    schema = ConfirmatorySchema.load(tmp_path)
    with pytest.raises(ValueError, match="adjudication"):
        schema.validate_phase_b_contract()


def test_phase_b_contract_rejects_paraphrased_source_manifest(tmp_path):
    _write_phase_b_fixture(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_capture_method"] = "Human-written paraphrases grounded in source pages."
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")

    schema = ConfirmatorySchema.load(tmp_path)
    with pytest.raises(ValueError, match="verbatim"):
        schema.validate_phase_b_contract()


def test_phase_b_contract_rejects_label_leaking_path_id(tmp_path):
    _write_phase_b_fixture(tmp_path)
    edge_path = tmp_path / "claim_edges.jsonl"
    edges = [json.loads(line) for line in edge_path.read_text(encoding="utf-8").splitlines()]
    edges[0]["path_ids"] = ["pb_t01_gap_path"]
    edges[1]["path_ids"] = ["pb_t01_gap_path"]
    _write_jsonl(edge_path, edges)
    _rehash_manifest(tmp_path, "claim_edges.jsonl")

    schema = ConfirmatorySchema.load(tmp_path)
    with pytest.raises(ValueError, match="IDs leak"):
        schema.validate_phase_b_contract()
