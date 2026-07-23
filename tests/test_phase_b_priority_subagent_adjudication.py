"""Tests for the owner-authorized priority subagent source gate."""

from __future__ import annotations

import json
from pathlib import Path

from benchmarks.knowledge_state_search.phase_b_priority_subagent_adjudication import (
    validate_priority_subagent_adjudication,
)


def test_priority_subagent_finalizes_all_sources_without_claiming_human_review(
    tmp_path: Path,
):
    paths = _fixture(tmp_path, second_status="verified")

    report = validate_priority_subagent_adjudication(
        action_packet_path=paths["actions"],
        subagent_results_path=paths["results"],
        subagent_summary_path=paths["summary"],
        verification_report_path=paths["verification"],
    )

    assert report["status"] == "pass"
    assert report["final_decision"] is True
    assert report["no_further_model_review_required"] is True
    assert report["decision_authority"] == "dataset_owner_authorized_priority_subagent"
    assert report["final_source_verified_count"] == 3
    assert report["human_verified_count"] == 0
    assert report["source_verification_gate_complete"] is True
    assert report["blind_annotation_authorized"] is True
    assert report["method_runs_authorized"] is False


def test_priority_subagent_nonverified_result_keeps_gate_closed(tmp_path: Path):
    paths = _fixture(tmp_path, second_status="needs_context")

    report = validate_priority_subagent_adjudication(
        action_packet_path=paths["actions"],
        subagent_results_path=paths["results"],
        subagent_summary_path=paths["summary"],
        verification_report_path=paths["verification"],
    )

    assert report["status"] == "priority_review_gate_failed"
    assert report["priority_nonverified_source_ids"] == ["pb_t02_s01"]
    assert report["source_verification_gate_complete"] is False
    assert report["blind_annotation_authorized"] is False


def _fixture(tmp_path: Path, *, second_status: str) -> dict[str, Path]:
    paths = {
        "actions": tmp_path / "actions.jsonl",
        "results": tmp_path / "results.jsonl",
        "summary": tmp_path / "summary.json",
        "verification": tmp_path / "verification.json",
    }
    _write_jsonl(
        paths["actions"],
        [
            {
                "source_id": "pb_t01_s01",
                "action_id": "human_adjudication:pb_t01_s01",
                "action_type": "adjudication",
            },
            {
                "source_id": "pb_t02_s01",
                "action_id": "human_spot_check:pb_t02_s01",
                "action_type": "spot_check",
            },
        ],
    )
    _write_jsonl(
        paths["results"],
        [
            _result(
                "pb_t01_s01",
                "human_adjudication:pb_t01_s01",
                "adjudication",
                "verified",
            ),
            _result(
                "pb_t02_s01",
                "human_spot_check:pb_t02_s01",
                "spot_check",
                second_status,
            ),
        ],
    )
    paths["summary"].write_text(
        json.dumps(
            {
                "review_count": 2,
                "human_verified_count": 0,
                "final_decision": True,
                "no_further_model_review_required": True,
            }
        ),
        encoding="utf-8",
    )
    paths["verification"].write_text(
        json.dumps(
            {
                "source_count": 3,
                "human_review_action_count": 2,
                "disposition_counts": {
                    "model_consensus_verified": 2,
                    "human_adjudication_required": 1,
                    "repair_required": 0,
                },
            }
        ),
        encoding="utf-8",
    )
    return paths


def _result(
    source_id: str,
    action_id: str,
    action_type: str,
    status: str,
) -> dict[str, object]:
    return {
        "source_id": source_id,
        "action_id": action_id,
        "action_type": action_type,
        "status": status,
        "reviewer_kind": "subagent_model",
        "reviewer_id": "model:codex-subagent",
        "evidence": {"excerpt_exact_match": True},
        "notes": "Test-only priority decision.",
    }


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, separators=(",", ":")) for row in rows) + "\n",
        encoding="utf-8",
    )
