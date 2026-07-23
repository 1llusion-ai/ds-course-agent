"""Tests for Phase B real-human result ingestion."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.knowledge_state_search.phase_b_human_review_results import (
    validate_human_review_results,
)


def test_human_result_ingestion_requires_full_real_reviewer_coverage(tmp_path: Path):
    actions, verification_report = _action_fixture(tmp_path)
    results = tmp_path / "results.jsonl"
    _write_jsonl(
        results,
        [
            _result("pb_t01_s01", "verified", "xiaofan"),
            _result("pb_t02_s01", "verified", "reviewer-b"),
        ],
    )

    report = validate_human_review_results(
        results,
        action_packet_path=actions,
        verification_report_path=verification_report,
    )

    assert report["status"] == "pass"
    assert report["result_count"] == 2
    assert report["unique_reviewer_count"] == 2
    assert report["final_source_verified_count"] == 3
    assert report["source_verification_gate_complete"] is True
    assert report["blind_annotation_authorized"] is True
    assert report["method_runs_authorized"] is False


def test_human_result_ingestion_rejects_missing_coverage(tmp_path: Path):
    actions, verification_report = _action_fixture(tmp_path)
    results = tmp_path / "results.jsonl"
    _write_jsonl(results, [_result("pb_t01_s01", "verified", "xiaofan")])

    with pytest.raises(ValueError, match="coverage mismatch"):
        validate_human_review_results(
            results,
            action_packet_path=actions,
            verification_report_path=verification_report,
        )


@pytest.mark.parametrize("reviewer_id", ["doubao", "mimo", "agent:source-check"])
def test_human_result_ingestion_rejects_model_or_agent_identity(
    tmp_path: Path,
    reviewer_id: str,
):
    actions, verification_report = _action_fixture(tmp_path)
    results = tmp_path / "results.jsonl"
    _write_jsonl(
        results,
        [
            _result("pb_t01_s01", "verified", reviewer_id),
            _result("pb_t02_s01", "verified", "xiaofan"),
        ],
    )

    with pytest.raises(ValueError, match="not a real human identity"):
        validate_human_review_results(
            results,
            action_packet_path=actions,
            verification_report_path=verification_report,
        )


def test_failed_spot_check_blocks_annotation_and_requires_reaudit(tmp_path: Path):
    actions, verification_report = _action_fixture(tmp_path)
    results = tmp_path / "results.jsonl"
    _write_jsonl(
        results,
        [
            _result("pb_t01_s01", "verified", "xiaofan"),
            _result("pb_t02_s01", "needs_context", "xiaofan"),
        ],
    )

    report = validate_human_review_results(
        results,
        action_packet_path=actions,
        verification_report_path=verification_report,
    )

    assert report["status"] == "valid_results_gate_failed"
    assert report["spot_check_nonverified_source_ids"] == ["pb_t02_s01"]
    assert report["full_consensus_reaudit_required"] is True
    assert report["blind_annotation_authorized"] is False


def _action_fixture(tmp_path: Path) -> tuple[Path, Path]:
    actions = tmp_path / "actions.jsonl"
    verification_report = tmp_path / "verification_report.json"
    _write_jsonl(
        actions,
        [
            {
                "source_id": "pb_t01_s01",
                "action_type": "adjudication",
                "action_id": "human_adjudication:pb_t01_s01",
            },
            {
                "source_id": "pb_t02_s01",
                "action_type": "spot_check",
                "action_id": "human_spot_check:pb_t02_s01",
            },
        ],
    )
    verification_report.write_text(
        json.dumps(
            {
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
    return actions, verification_report


def _result(
    source_id: str,
    status: str,
    reviewer_id: str,
) -> dict[str, str]:
    return {
        "source_id": source_id,
        "status": status,
        "reviewer_id": reviewer_id,
        "reviewed_at": "2026-07-23T12:00:00+08:00",
        "notes": "Test-only review result.",
    }


def _write_jsonl(path: Path, rows: list[dict[str, str]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, separators=(",", ":")) for row in rows) + "\n",
        encoding="utf-8",
    )
