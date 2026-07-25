"""Tests for terminal priority-subagent relation adjudication."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.knowledge_state_search.phase_b_annotation_packet_contract import (
    file_sha256,
)
from benchmarks.knowledge_state_search.phase_b_relation_priority_adjudication import (
    finalize_priority_relation_adjudication,
)


def test_priority_subagent_finalizes_disagreement_and_can_flip_spot_check(tmp_path: Path):
    paths = _fixture(tmp_path, spot_needs_context=False)

    report = finalize_priority_relation_adjudication(
        consensus_path=paths["consensus"],
        source_scope_labels_path=paths["scope_labels"],
        source_scope_report_path=paths["scope_report"],
        expected_source_scope_count=3,
        action_manifest_path=paths["manifest"],
        action_packet_path=paths["packet"],
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
    assert report["fixed_source_scope_applied"] is True
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
        source_scope_labels_path=paths["scope_labels"],
        source_scope_report_path=paths["scope_report"],
        expected_source_scope_count=3,
        action_manifest_path=paths["manifest"],
        action_packet_path=paths["packet"],
        action_map_path=paths["action_map"],
        priority_results_path=paths["results"],
        output_report_path=paths["report"],
        final_labels_path=paths["labels"],
        unresolved_path=paths["unresolved"],
    )

    assert report["status"] == "priority_repair_required"
    assert report["unresolved_repair_count"] == 1
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
            source_scope_labels_path=paths["scope_labels"],
            source_scope_report_path=paths["scope_report"],
            expected_source_scope_count=3,
            action_manifest_path=paths["manifest"],
            action_packet_path=paths["packet"],
            action_map_path=paths["action_map"],
            priority_results_path=paths["results"],
            output_report_path=paths["report"],
            final_labels_path=paths["labels"],
            unresolved_path=paths["unresolved"],
        )


def test_priority_non_absent_evidence_under_out_of_scope_requires_repair(
    tmp_path: Path,
) -> None:
    paths = _fixture(tmp_path, spot_needs_context=False)
    packet = _read_jsonl(paths["packet"])
    action_map = _read_jsonl(paths["action_map"])
    consensus = _read_jsonl(paths["consensus"])
    scope_labels = _read_jsonl(paths["scope_labels"])
    packet[1]["fixed_task_scope"] = "out_of_scope"
    action_map[1]["fixed_task_scope"] = "out_of_scope"
    scope_labels[2]["task_scope"] = "out_of_scope"
    consensus[2]["consensus_relation"] = None
    consensus[2]["disposition"] = "source_scope_repair_required"
    consensus[2]["reason"] = "source_scope_relation_conflict"
    consensus[2]["source_scope_relation_conflict"] = True
    for summary in consensus[2]["reviewer_judgments"].values():
        summary["fixed_task_scope"] = "out_of_scope"
        summary["source_scope_conflict"] = True
    _write_jsonl(paths["packet"], packet)
    _write_jsonl(paths["action_map"], action_map)
    _write_jsonl(paths["consensus"], consensus)
    _write_jsonl(paths["scope_labels"], scope_labels)
    scope_report = json.loads(paths["scope_report"].read_text(encoding="utf-8"))
    scope_report["artifact_hashes"]["final_labels_sha256"] = file_sha256(paths["scope_labels"])
    paths["scope_report"].write_text(
        json.dumps(scope_report) + "\n",
        encoding="utf-8",
    )
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    manifest["packet_sha256"] = file_sha256(paths["packet"])
    manifest["private_map_sha256"] = file_sha256(paths["action_map"])
    paths["manifest"].write_text(
        json.dumps(manifest) + "\n",
        encoding="utf-8",
    )

    report = finalize_priority_relation_adjudication(
        consensus_path=paths["consensus"],
        source_scope_labels_path=paths["scope_labels"],
        source_scope_report_path=paths["scope_report"],
        expected_source_scope_count=3,
        action_manifest_path=paths["manifest"],
        action_packet_path=paths["packet"],
        action_map_path=paths["action_map"],
        priority_results_path=paths["results"],
        output_report_path=paths["report"],
        final_labels_path=paths["labels"],
        unresolved_path=paths["unresolved"],
    )

    assert report["status"] == "priority_repair_required"
    assert report["priority_source_scope_conflict_count"] == 1
    assert report["unresolved_repair_count"] == 1
    assert _read_jsonl(paths["unresolved"])[0]["reason"] == "priority_source_scope_relation_conflict"


def _fixture(tmp_path: Path, *, spot_needs_context: bool) -> dict[str, Path]:
    paths = {
        "consensus": tmp_path / "consensus.jsonl",
        "manifest": tmp_path / "manifest.json",
        "packet": tmp_path / "packet.jsonl",
        "action_map": tmp_path / "action_map.jsonl",
        "results": tmp_path / "results.jsonl",
        "report": tmp_path / "report.json",
        "labels": tmp_path / "labels.jsonl",
        "unresolved": tmp_path / "unresolved.jsonl",
        "scope_labels": tmp_path / "scope" / "model_proxy_source_scope_labels.jsonl",
        "scope_report": tmp_path / "scope" / "priority_adjudication_report.json",
    }
    _write_scope_provenance(paths["scope_labels"], paths["scope_report"])
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
    _write_jsonl(
        paths["packet"],
        [
            _packet("p_0001", "Contrary evidence."),
            _packet("p_0002", "Weaker evidence."),
        ],
    )
    paths["manifest"].write_text(
        json.dumps(
            {
                "protocol": "phase_b_relation_priority_subagent_v3",
                "priority_rule": "subagent_decision_is_terminal",
                "no_recursive_model_review": True,
                "fixed_source_scope_visible_to_subagent": True,
                "action_count": 2,
                "packet_sha256": file_sha256(paths["packet"]),
                "private_map_sha256": file_sha256(paths["action_map"]),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _write_jsonl(
        paths["results"],
        [
            _result("p_0001", "contradicted", "Contrary evidence.", False),
            _result("p_0002", "weaker", "Weaker evidence.", spot_needs_context),
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
    doubao_relation = relation or "supported"
    gemini_relation = relation or "partial"
    return {
        "task_id": task_id,
        "target_type": "claim",
        "target_id": f"{task_id}_{target_suffix}",
        "source_id": f"{task_id}_{source_suffix}",
        "reviewer_judgments": {
            "doubao": _lower_summary("doubao", doubao_relation),
            "gemini": _lower_summary("gemini", gemini_relation),
        },
        "relation_agreement": relation is not None,
        "routing_agreement": relation is not None,
        "source_scope_relation_conflict": False,
        "consensus_relation": relation,
        "disposition": disposition,
        "reason": (
            "same_relation_without_context_flag" if disposition == "dual_model_consensus" else "relation_disagreement"
        ),
        "human_verified": False,
        "model_only_proxy": True,
    }


def _lower_summary(
    reviewer_id: str,
    relation: str,
) -> dict[str, object]:
    status_by_relation = {
        "supported": "entailed",
        "partial": "weaker",
        "contradicted": "contradicted",
        "distractor": "absent",
        "unrelated": "absent",
    }
    status = status_by_relation[relation]
    return {
        "blind_item_id": f"{reviewer_id[0]}_synthetic",
        "model": f"{reviewer_id}-model",
        "fixed_task_scope": "in_scope",
        "source_scope_conflict": False,
        "proposition_checks": [
            {
                "proposition_id": "p1",
                "status": status,
                "evidence_sentence_ids": [] if status == "absent" else ["s1"],
                "evidence_quote": None if status == "absent" else "Synthetic evidence.",
            }
        ],
        "relation": relation,
        "needs_context": False,
        "notes": "Synthetic lower-model judgment.",
        "input_sha256": "0" * 64,
        "request_nonce": f"nonce-{reviewer_id}",
        "provider_response_id": None,
        "response_body_sha256": "1" * 64,
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
        "fixed_task_scope": "in_scope",
        "lower_priority_judgments": consensus["reviewer_judgments"],
    }


def _packet(
    blind_item_id: str,
    excerpt: str,
) -> dict[str, object]:
    return {
        "blind_item_id": blind_item_id,
        "task_question": "Synthetic question?",
        "target_text": "Synthetic target.",
        "target_type": "claim",
        "atomic_propositions": [
            {
                "proposition_id": "p1",
                "text": "Synthetic proposition.",
            }
        ],
        "edge_type": None,
        "source_title": "Synthetic source",
        "source_url": "https://example.invalid/source",
        "source_excerpt": excerpt,
        "source_sentences": [{"sentence_id": "s1", "text": excerpt}],
        "fixed_task_scope": "in_scope",
    }


def _result(
    blind_item_id: str,
    status: str,
    evidence_quote: str,
    needs_context: bool,
) -> dict[str, object]:
    return {
        "blind_item_id": blind_item_id,
        "proposition_checks": [
            {
                "proposition_id": "p1",
                "status": status,
                "evidence_sentence_ids": ["s1"],
            }
        ],
        "needs_context": needs_context,
        "notes": "Priority subagent test decision.",
        "reviewer_kind": "subagent_model",
        "reviewer_id": "model:codex-priority-subagent",
        "model": "gpt-5.6-sol",
    }


def _write_scope_provenance(
    labels_path: Path,
    report_path: Path,
) -> None:
    labels_path.parent.mkdir(parents=True)
    _write_jsonl(
        labels_path,
        [
            {
                "task_id": f"pb_t0{index}",
                "source_id": f"pb_t0{index}_s01",
                "task_scope": "in_scope",
            }
            for index in range(1, 4)
        ],
    )
    artifact_names = {
        "consensus_sha256": "dual_model_scope_consensus.jsonl",
        "action_manifest_sha256": "priority_action_manifest.json",
        "action_map_sha256": "data_lead_priority_action_map.jsonl",
        "priority_results_sha256": "priority_subagent_results.jsonl",
        "unresolved_sha256": "priority_unresolved_queue.jsonl",
    }
    artifact_hashes: dict[str, str] = {}
    for hash_field, filename in artifact_names.items():
        path = report_path.parent / filename
        path.write_text("", encoding="utf-8")
        artifact_hashes[hash_field] = file_sha256(path)
    artifact_hashes["final_labels_sha256"] = file_sha256(labels_path)
    report_path.write_text(
        json.dumps(
            {
                "status": "model_proxy_source_scope_annotation_complete",
                "annotation_basis": "dual_model_consensus_plus_priority_subagent",
                "model_only_proxy": True,
                "human_verified_count": 0,
                "priority_decision_is_terminal": True,
                "no_recursive_model_review": True,
                "unresolved_context_count": 0,
                "model_proxy_labels_finalized": 3,
                "full_model_proxy_annotation_complete": True,
                "artifact_hashes": artifact_hashes,
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )
