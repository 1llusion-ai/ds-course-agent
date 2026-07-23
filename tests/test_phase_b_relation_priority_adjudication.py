"""Tests for terminal priority-subagent relation adjudication."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.knowledge_state_search.phase_b_relation_priority_adjudication import (
    finalize_priority_relation_adjudication,
)


def test_priority_subagent_finalizes_disagreement_and_can_flip_spot_check(tmp_path: Path):
    paths = _fixture(tmp_path, spot_needs_context=False)

    report = finalize_priority_relation_adjudication(
        consensus_path=paths["consensus"],
        action_manifest_path=paths["manifest"],
        action_map_path=paths["action_map"],
        priority_results_path=paths["results"],
        output_report_path=paths["report"],
        final_labels_path=paths["labels"],
        unresolved_path=paths["unresolved"],
    )

    labels = _read_jsonl(paths["labels"])
    assert report["status"] == "selected_model_proxy_annotation_complete"
    assert report["priority_action_count"] == 2
    assert report["priority_adjudication_count"] == 1
    assert report["priority_spot_check_count"] == 1
    assert report["priority_flip_count"] == 1
    assert report["priority_spot_check_flip_count"] == 1
    assert report["model_proxy_annotations_finalized"] == 3
    assert report["human_verified_count"] == 0
    assert report["priority_decision_is_terminal"] is True
    assert report["method_runs_authorized"] is False
    assert [row["relation"] for row in labels] == [
        "supported",
        "contradicted",
        "partial",
    ]
    assert _read_jsonl(paths["unresolved"]) == []


def test_priority_needs_context_keeps_pair_out_of_final_proxy_labels(tmp_path: Path):
    paths = _fixture(tmp_path, spot_needs_context=True)

    report = finalize_priority_relation_adjudication(
        consensus_path=paths["consensus"],
        action_manifest_path=paths["manifest"],
        action_map_path=paths["action_map"],
        priority_results_path=paths["results"],
        output_report_path=paths["report"],
        final_labels_path=paths["labels"],
        unresolved_path=paths["unresolved"],
    )

    assert report["status"] == "priority_context_repair_required"
    assert report["unresolved_context_count"] == 1
    assert report["model_proxy_annotations_finalized"] == 2
    assert report["selected_pairs_finalized"] is False
    assert len(_read_jsonl(paths["unresolved"])) == 1


def test_priority_result_rejects_non_subagent_identity(tmp_path: Path):
    paths = _fixture(tmp_path, spot_needs_context=False)
    results = _read_jsonl(paths["results"])
    results[0]["reviewer_id"] = "human-reviewer"
    _write_jsonl(paths["results"], results)

    with pytest.raises(ValueError, match="priority reviewer_id is invalid"):
        finalize_priority_relation_adjudication(
            consensus_path=paths["consensus"],
            action_manifest_path=paths["manifest"],
            action_map_path=paths["action_map"],
            priority_results_path=paths["results"],
            output_report_path=paths["report"],
            final_labels_path=paths["labels"],
            unresolved_path=paths["unresolved"],
        )


def _fixture(tmp_path: Path, *, spot_needs_context: bool) -> dict[str, Path]:
    paths = {
        "consensus": tmp_path / "consensus.jsonl",
        "manifest": tmp_path / "manifest.json",
        "action_map": tmp_path / "action_map.jsonl",
        "results": tmp_path / "results.jsonl",
        "report": tmp_path / "report.json",
        "labels": tmp_path / "labels.jsonl",
        "unresolved": tmp_path / "unresolved.jsonl",
    }
    consensus = [
        _consensus("pb_t01", "c01", "s01", "supported", "dual_model_consensus"),
        _consensus("pb_t02", "c01", "s01", None, "priority_subagent_required"),
        _consensus("pb_t03", "c01", "s01", "supported", "dual_model_consensus"),
    ]
    _write_jsonl(paths["consensus"], consensus)
    action_map = [
        _action("p_0001", "adjudication", consensus[1]),
        _action("p_0002", "spot_check", consensus[2]),
    ]
    _write_jsonl(paths["action_map"], action_map)
    paths["manifest"].write_text(
        json.dumps(
            {
                "priority_rule": "subagent_decision_is_terminal",
                "no_recursive_model_review": True,
                "action_count": 2,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _write_jsonl(
        paths["results"],
        [
            _result("p_0001", "contradicted", False),
            _result("p_0002", "partial", spot_needs_context),
        ],
    )
    return paths


def _consensus(
    task_id: str,
    target_suffix: str,
    source_suffix: str,
    relation: str | None,
    disposition: str,
) -> dict[str, object]:
    return {
        "task_id": task_id,
        "target_type": "claim",
        "target_id": f"{task_id}_{target_suffix}",
        "source_id": f"{task_id}_{source_suffix}",
        "reviewer_judgments": {
            "doubao": {"relation": relation or "supported"},
            "mimo": {"relation": relation or "partial"},
        },
        "relation_agreement": relation is not None,
        "exact_judgment_agreement": relation is not None,
        "consensus_relation": relation,
        "disposition": disposition,
        "reason": "test",
        "human_verified": False,
        "model_only_proxy": True,
    }


def _action(
    blind_item_id: str,
    action_type: str,
    consensus: dict[str, object],
) -> dict[str, object]:
    return {
        "priority_blind_item_id": blind_item_id,
        "action_id": f"priority_relation:{blind_item_id}",
        "action_type": action_type,
        "task_id": consensus["task_id"],
        "target_type": consensus["target_type"],
        "target_id": consensus["target_id"],
        "source_id": consensus["source_id"],
        "lower_priority_judgments": consensus["reviewer_judgments"],
    }


def _result(
    blind_item_id: str,
    relation: str,
    needs_context: bool,
) -> dict[str, object]:
    return {
        "blind_item_id": blind_item_id,
        "relation": relation,
        "needs_context": needs_context,
        "notes": "Priority subagent test decision.",
        "reviewer_kind": "subagent_model",
        "reviewer_id": "model:codex-priority-subagent",
        "model": "gpt-5.6-sol",
    }


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )
