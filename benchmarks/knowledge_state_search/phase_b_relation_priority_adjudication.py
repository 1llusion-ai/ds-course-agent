"""Finalize model-proxy relation labels with the priority subagent."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from benchmarks.knowledge_state_search.phase_b_annotation_packet_contract import (
    file_sha256,
)
from benchmarks.knowledge_state_search.phase_b_relation_annotation import (
    DEFAULT_OUTPUT_DIRECTORY,
)
from benchmarks.knowledge_state_search.phase_b_relation_annotation_contract import (
    PROPOSITION_LABEL_SET,
    AtomicProposition,
    PropositionCheck,
    derive_relation,
    parse_proposition_checks,
    required_string,
)
from benchmarks.knowledge_state_search.phase_b_relation_annotation_support import (
    DEFAULT_SOURCE_SCOPE_LABELS_PATH,
    DEFAULT_SOURCE_SCOPE_REPORT_PATH,
    PRIORITY_PACKET_FIELDS,
    SourceScopeKey,
    load_source_scope_labels,
    validate_source_scope_provenance,
)
from benchmarks.knowledge_state_search.phase_b_source_scope_annotation_contract import (
    TASK_SCOPE_LABEL_SET,
)

DEFAULT_CONSENSUS_PATH = DEFAULT_OUTPUT_DIRECTORY / "dual_model_consensus.jsonl"
DEFAULT_ACTION_MANIFEST_PATH = DEFAULT_OUTPUT_DIRECTORY / "priority_action_manifest.json"
DEFAULT_ACTION_PACKET_PATH = DEFAULT_OUTPUT_DIRECTORY / "priority_action_packet.jsonl"
DEFAULT_ACTION_MAP_PATH = DEFAULT_OUTPUT_DIRECTORY / "data_lead_priority_action_map.jsonl"
DEFAULT_PRIORITY_RESULTS_PATH = DEFAULT_OUTPUT_DIRECTORY / "priority_subagent_results.jsonl"
DEFAULT_OUTPUT_REPORT_PATH = DEFAULT_OUTPUT_DIRECTORY / "priority_adjudication_report.json"
DEFAULT_FINAL_LABELS_PATH = DEFAULT_OUTPUT_DIRECTORY / "model_proxy_annotations.jsonl"
DEFAULT_UNRESOLVED_PATH = DEFAULT_OUTPUT_DIRECTORY / "priority_unresolved_queue.jsonl"
_PRIORITY_REVIEWER_ID = "model:codex-priority-subagent"
_PRIORITY_MODEL = "gpt-5.6-sol"
_RESULT_FIELDS = (
    "blind_item_id",
    "proposition_checks",
    "needs_context",
    "notes",
    "reviewer_kind",
    "reviewer_id",
    "model",
)


def finalize_priority_relation_adjudication(
    *,
    consensus_path: Path = DEFAULT_CONSENSUS_PATH,
    source_scope_labels_path: Path = DEFAULT_SOURCE_SCOPE_LABELS_PATH,
    source_scope_report_path: Path = DEFAULT_SOURCE_SCOPE_REPORT_PATH,
    expected_source_scope_count: int = 144,
    action_manifest_path: Path = DEFAULT_ACTION_MANIFEST_PATH,
    action_packet_path: Path = DEFAULT_ACTION_PACKET_PATH,
    action_map_path: Path = DEFAULT_ACTION_MAP_PATH,
    priority_results_path: Path = DEFAULT_PRIORITY_RESULTS_PATH,
    output_report_path: Path = DEFAULT_OUTPUT_REPORT_PATH,
    final_labels_path: Path = DEFAULT_FINAL_LABELS_PATH,
    unresolved_path: Path = DEFAULT_UNRESOLVED_PATH,
) -> dict[str, object]:
    """Apply terminal priority decisions without claiming human annotation."""

    consensus_rows = _read_jsonl(consensus_path)
    source_scope_by_key = load_source_scope_labels(
        source_scope_labels_path,
        expected_count=expected_source_scope_count,
    )
    validate_source_scope_provenance(
        labels_path=source_scope_labels_path,
        report_path=source_scope_report_path,
        expected_count=expected_source_scope_count,
    )
    action_manifest = json.loads(action_manifest_path.read_text(encoding="utf-8"))
    action_packet_rows = _read_jsonl(action_packet_path)
    action_rows = _read_jsonl(action_map_path)
    result_rows = _read_jsonl(priority_results_path)
    if action_manifest.get("protocol") != "phase_b_relation_priority_subagent_v2":
        raise ValueError("priority action manifest protocol is invalid")
    if action_manifest.get("priority_rule") != "subagent_decision_is_terminal":
        raise ValueError("priority action manifest lacks the terminal-decision rule")
    if action_manifest.get("no_recursive_model_review") is not True:
        raise ValueError("priority action manifest must close recursive model review")
    if action_manifest.get("fixed_source_scope_visible_to_subagent") is not True:
        raise ValueError("priority action manifest must expose fixed source scope")
    if int(action_manifest.get("action_count", -1)) != len(action_rows):
        raise ValueError("priority action manifest count does not match the private map")
    if action_manifest.get("packet_sha256") != file_sha256(action_packet_path):
        raise ValueError("priority action packet hash mismatch")
    if action_manifest.get("private_map_sha256") != file_sha256(action_map_path):
        raise ValueError("priority action map hash mismatch")

    packet_by_blind_id = _unique_rows(action_packet_rows, "blind_item_id", "priority packet")
    action_by_blind_id = _unique_rows(action_rows, "priority_blind_item_id", "priority action")
    result_by_blind_id = _unique_rows(result_rows, "blind_item_id", "priority result")
    if set(packet_by_blind_id) != set(action_by_blind_id):
        raise ValueError("priority packet/private map coverage mismatch")
    if set(result_by_blind_id) != set(action_by_blind_id):
        raise ValueError(
            "priority result coverage mismatch: "
            f"missing={sorted(set(action_by_blind_id) - set(result_by_blind_id))}, "
            f"extra={sorted(set(result_by_blind_id) - set(action_by_blind_id))}"
        )
    validated_results = {
        blind_item_id: _validate_priority_result(
            result,
            packet=packet_by_blind_id[blind_item_id],
        )
        for blind_item_id, result in result_by_blind_id.items()
    }

    action_by_key: dict[tuple[str, str, str, str], tuple[dict[str, Any], dict[str, Any]]] = {}
    for blind_item_id, action in action_by_blind_id.items():
        key = _canonical_key(action)
        if key in action_by_key:
            raise ValueError(f"priority action map duplicates a canonical pair: {key}")
        fixed_task_scope = required_string(action, "fixed_task_scope")
        if fixed_task_scope not in TASK_SCOPE_LABEL_SET:
            raise ValueError(f"priority action has invalid fixed_task_scope: {key}")
        if required_string(packet_by_blind_id[blind_item_id], "fixed_task_scope") != fixed_task_scope:
            raise ValueError(f"priority packet/action fixed_task_scope mismatch: {key}")
        action_by_key[key] = (action, validated_results[blind_item_id])

    final_labels: list[dict[str, str]] = []
    unresolved: list[dict[str, object]] = []
    priority_flip_count = 0
    priority_spot_check_flip_count = 0
    priority_adjudication_count = 0
    priority_spot_check_count = 0
    priority_source_scope_conflict_count = 0
    seen_keys: set[tuple[str, str, str, str]] = set()
    for row in consensus_rows:
        key = _canonical_key(row)
        if key in seen_keys:
            raise ValueError(f"dual-model consensus duplicates a canonical pair: {key}")
        seen_keys.add(key)
        try:
            fixed_task_scope = source_scope_by_key[SourceScopeKey(task_id=key[0], source_id=key[3])]
        except KeyError as exc:
            raise ValueError(f"finalizer lacks fixed source scope: {key}") from exc
        validated_consensus_relation = _validate_consensus_derivation(
            row,
            key=key,
            fixed_task_scope=fixed_task_scope,
        )
        action_result = action_by_key.get(key)
        if action_result is None:
            if row.get("disposition") == "source_scope_repair_required":
                unresolved.append(
                    {
                        **_canonical_row(key),
                        "action_type": None,
                        "priority_relation": None,
                        "priority_notes": None,
                        "reason": "lower_model_source_scope_relation_conflict",
                        "repair_required": True,
                    }
                )
                continue
            if row.get("disposition") != "dual_model_consensus":
                raise ValueError(f"unrouted non-consensus relation pair: {key}")
            if validated_consensus_relation is None:
                raise ValueError(f"clean consensus lacks a validated relation: {key}")
            final_labels.append(_final_label(key, validated_consensus_relation))
            continue

        action, result = action_result
        action_type = required_string(action, "action_type")
        if action_type == "adjudication":
            if row.get("disposition") != "priority_subagent_required":
                raise ValueError(f"priority adjudication action is misrouted: {key}")
            priority_adjudication_count += 1
        elif action_type == "spot_check":
            if row.get("disposition") != "dual_model_consensus":
                raise ValueError(f"priority spot-check action is misrouted: {key}")
            priority_spot_check_count += 1
        else:
            raise ValueError(f"invalid priority action_type: {action_type}")
        if result["source_scope_conflict"] is True:
            priority_source_scope_conflict_count += 1
        if result["needs_context"] is True or result["source_scope_conflict"] is True:
            unresolved.append(
                {
                    **_canonical_row(key),
                    "action_type": action_type,
                    "priority_relation": result["relation"],
                    "priority_notes": result["notes"],
                    "reason": (
                        "priority_source_scope_relation_conflict"
                        if result["source_scope_conflict"] is True
                        else "priority_subagent_needs_context"
                    ),
                    "repair_required": True,
                }
            )
            continue
        relation = str(result["relation"])
        consensus_relation = row.get("consensus_relation")
        if isinstance(consensus_relation, str) and consensus_relation != relation:
            priority_flip_count += 1
            if action_type == "spot_check":
                priority_spot_check_flip_count += 1
        final_labels.append(_final_label(key, relation))

    if set(action_by_key) - seen_keys:
        raise ValueError("priority action map references unknown consensus pairs")
    final_labels.sort(
        key=lambda row: (
            row["task_id"],
            row["target_type"],
            row["target_id"],
            row["source_id"],
        )
    )
    unresolved.sort(
        key=lambda row: (
            str(row["task_id"]),
            str(row["target_type"]),
            str(row["target_id"]),
            str(row["source_id"]),
        )
    )
    _write_jsonl(final_labels_path, final_labels)
    _write_jsonl(unresolved_path, unresolved)
    selected_pair_count = len(consensus_rows)
    selected_pairs_finalized = len(final_labels) == selected_pair_count
    full_proxy_annotation_complete = selected_pair_count == 1440 and selected_pairs_finalized
    report = {
        "status": (
            "model_proxy_annotation_complete"
            if full_proxy_annotation_complete
            else (
                "selected_model_proxy_annotation_complete" if selected_pairs_finalized else "priority_repair_required"
            )
        ),
        "annotation_basis": "dual_model_consensus_plus_priority_subagent",
        "model_only_proxy": True,
        "human_verified_count": 0,
        "priority_reviewer_kind": "subagent_model",
        "priority_reviewer_id": _PRIORITY_REVIEWER_ID,
        "priority_decision_is_terminal": True,
        "no_recursive_model_review": True,
        "fixed_source_scope_applied": True,
        "selected_canonical_pair_count": selected_pair_count,
        "priority_action_count": len(action_rows),
        "priority_adjudication_count": priority_adjudication_count,
        "priority_spot_check_count": priority_spot_check_count,
        "priority_flip_count": priority_flip_count,
        "priority_spot_check_flip_count": priority_spot_check_flip_count,
        "priority_source_scope_conflict_count": priority_source_scope_conflict_count,
        "unresolved_repair_count": len(unresolved),
        "model_proxy_annotations_finalized": len(final_labels),
        "selected_pairs_finalized": selected_pairs_finalized,
        "full_model_proxy_annotation_complete": full_proxy_annotation_complete,
        "annotation_started": True,
        "dataset_frozen": False,
        "method_runs_authorized": False,
    }
    output_report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def build_parser() -> argparse.ArgumentParser:
    """Build the priority relation-adjudication CLI."""

    parser = argparse.ArgumentParser(description="Finalize Phase B model-proxy labels with the priority subagent.")
    parser.add_argument("--consensus", type=Path, default=DEFAULT_CONSENSUS_PATH)
    parser.add_argument(
        "--source-scope-labels",
        type=Path,
        default=DEFAULT_SOURCE_SCOPE_LABELS_PATH,
    )
    parser.add_argument(
        "--source-scope-report",
        type=Path,
        default=DEFAULT_SOURCE_SCOPE_REPORT_PATH,
    )
    parser.add_argument("--expected-source-scope-count", type=int, default=144)
    parser.add_argument("--action-manifest", type=Path, default=DEFAULT_ACTION_MANIFEST_PATH)
    parser.add_argument("--action-packet", type=Path, default=DEFAULT_ACTION_PACKET_PATH)
    parser.add_argument("--action-map", type=Path, default=DEFAULT_ACTION_MAP_PATH)
    parser.add_argument("--results", type=Path, default=DEFAULT_PRIORITY_RESULTS_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_REPORT_PATH)
    parser.add_argument("--final-labels", type=Path, default=DEFAULT_FINAL_LABELS_PATH)
    parser.add_argument("--unresolved", type=Path, default=DEFAULT_UNRESOLVED_PATH)
    return parser


def main() -> int:
    """Validate priority results and print the terminal model-only report."""

    args = build_parser().parse_args()
    report = finalize_priority_relation_adjudication(
        consensus_path=args.consensus,
        source_scope_labels_path=args.source_scope_labels,
        source_scope_report_path=args.source_scope_report,
        expected_source_scope_count=args.expected_source_scope_count,
        action_manifest_path=args.action_manifest,
        action_packet_path=args.action_packet,
        action_map_path=args.action_map,
        priority_results_path=args.results,
        output_report_path=args.output,
        final_labels_path=args.final_labels,
        unresolved_path=args.unresolved,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _validate_consensus_derivation(
    row: dict[str, Any],
    *,
    key: tuple[str, str, str, str],
    fixed_task_scope: str,
) -> str | None:
    judgments = row.get("reviewer_judgments")
    if not isinstance(judgments, dict) or set(judgments) != {"doubao", "mimo"}:
        raise ValueError(f"consensus reviewer coverage is invalid: {key}")
    derived_relations: dict[str, str] = {}
    needs_context: dict[str, bool] = {}
    source_scope_conflicts: dict[str, bool] = {}
    for reviewer_id in ("doubao", "mimo"):
        summary = judgments[reviewer_id]
        if not isinstance(summary, dict):
            raise ValueError(f"consensus reviewer summary is invalid: {key}/{reviewer_id}")
        if required_string(summary, "fixed_task_scope") != fixed_task_scope:
            raise ValueError(f"consensus fixed source scope mismatch: {key}/{reviewer_id}")
        checks = _consensus_proposition_checks(summary, key=key, reviewer_id=reviewer_id)
        derived_relation = derive_relation(
            target_type=key[1],
            task_scope=fixed_task_scope,
            proposition_checks=checks,
        )
        if required_string(summary, "relation") != derived_relation:
            raise ValueError(f"consensus reviewer relation derivation mismatch: {key}/{reviewer_id}")
        reviewer_needs_context = summary.get("needs_context")
        if not isinstance(reviewer_needs_context, bool):
            raise ValueError(f"consensus needs_context is invalid: {key}/{reviewer_id}")
        source_scope_conflict = fixed_task_scope == "out_of_scope" and any(check.status != "absent" for check in checks)
        if summary.get("source_scope_conflict") is not source_scope_conflict:
            raise ValueError(f"consensus source-scope conflict is invalid: {key}/{reviewer_id}")
        derived_relations[reviewer_id] = derived_relation
        needs_context[reviewer_id] = reviewer_needs_context
        source_scope_conflicts[reviewer_id] = source_scope_conflict

    relation_agreement = derived_relations["doubao"] == derived_relations["mimo"]
    routing_agreement = relation_agreement and needs_context["doubao"] == needs_context["mimo"]
    any_needs_context = any(needs_context.values())
    any_scope_conflict = any(source_scope_conflicts.values())
    if any_scope_conflict:
        expected_disposition = "source_scope_repair_required"
        expected_reason = "source_scope_relation_conflict"
        expected_consensus_relation = None
    elif routing_agreement and not any_needs_context:
        expected_disposition = "dual_model_consensus"
        expected_reason = "same_relation_without_context_flag"
        expected_consensus_relation = derived_relations["doubao"]
    else:
        expected_disposition = "priority_subagent_required"
        expected_reason = "context_uncertainty" if any_needs_context else "relation_disagreement"
        expected_consensus_relation = None
    expected_fields = {
        "relation_agreement": relation_agreement,
        "routing_agreement": routing_agreement,
        "source_scope_relation_conflict": any_scope_conflict,
        "consensus_relation": expected_consensus_relation,
        "disposition": expected_disposition,
        "reason": expected_reason,
    }
    for field_name, expected_value in expected_fields.items():
        if row.get(field_name) != expected_value:
            raise ValueError(f"consensus field is inconsistent: {key}/{field_name}")
    return expected_consensus_relation


def _consensus_proposition_checks(
    summary: dict[str, Any],
    *,
    key: tuple[str, str, str, str],
    reviewer_id: str,
) -> tuple[PropositionCheck, ...]:
    raw_checks = summary.get("proposition_checks")
    if not isinstance(raw_checks, list) or not raw_checks:
        raise ValueError(f"consensus proposition checks are invalid: {key}/{reviewer_id}")
    checks: list[PropositionCheck] = []
    seen: set[str] = set()
    for raw in raw_checks:
        if not isinstance(raw, dict) or set(raw) != {
            "proposition_id",
            "status",
            "evidence_quote",
        }:
            raise ValueError(f"consensus proposition check fields are invalid: {key}/{reviewer_id}")
        proposition_id = required_string(raw, "proposition_id")
        if proposition_id in seen:
            raise ValueError(f"consensus proposition check is duplicated: {key}/{reviewer_id}")
        seen.add(proposition_id)
        status = required_string(raw, "status")
        if status not in PROPOSITION_LABEL_SET:
            raise ValueError(f"consensus proposition status is invalid: {key}/{reviewer_id}")
        evidence_quote = raw.get("evidence_quote")
        if status == "absent":
            if evidence_quote is not None:
                raise ValueError(f"consensus absent evidence quote is invalid: {key}/{reviewer_id}")
        elif not isinstance(evidence_quote, str) or not evidence_quote.strip():
            raise ValueError(f"consensus non-absent evidence quote is invalid: {key}/{reviewer_id}")
        checks.append(
            PropositionCheck(
                proposition_id=proposition_id,
                status=status,
                evidence_quote=evidence_quote.strip() if isinstance(evidence_quote, str) else None,
            )
        )
    return tuple(checks)


def _validate_priority_result(
    payload: dict[str, Any],
    *,
    packet: dict[str, Any],
) -> dict[str, Any]:
    if tuple(payload) != _RESULT_FIELDS:
        raise ValueError("priority result field contract is invalid")
    if tuple(packet) != PRIORITY_PACKET_FIELDS:
        raise ValueError("priority packet field contract is invalid")
    if payload.get("reviewer_kind") != "subagent_model":
        raise ValueError("priority reviewer_kind must be subagent_model")
    if payload.get("reviewer_id") != _PRIORITY_REVIEWER_ID:
        raise ValueError("priority reviewer_id is invalid")
    if required_string(payload, "model") != _PRIORITY_MODEL:
        raise ValueError("priority model is invalid")
    blind_item_id = required_string(payload, "blind_item_id")
    if required_string(packet, "blind_item_id") != blind_item_id:
        raise ValueError("priority result/packet blind_item_id mismatch")
    propositions = _packet_propositions(packet)
    proposition_checks = parse_proposition_checks(
        payload,
        propositions,
        blind_item_id=blind_item_id,
        source_excerpt=required_string(packet, "source_excerpt"),
    )
    target_type = required_string(packet, "target_type")
    if target_type not in {"claim", "edge"}:
        raise ValueError(f"priority packet target_type is invalid: {target_type}")
    edge_type = packet.get("edge_type")
    if target_type == "claim" and edge_type is not None:
        raise ValueError("priority claim packet edge_type must be null")
    if target_type == "edge" and (not isinstance(edge_type, str) or not edge_type.strip()):
        raise ValueError("priority edge packet edge_type must be a non-empty string")
    fixed_task_scope = required_string(packet, "fixed_task_scope")
    if fixed_task_scope not in TASK_SCOPE_LABEL_SET:
        raise ValueError("priority packet fixed_task_scope is invalid")
    relation = derive_relation(
        target_type=target_type,
        task_scope=fixed_task_scope,
        proposition_checks=proposition_checks,
    )
    source_scope_conflict = fixed_task_scope == "out_of_scope" and any(
        check.status != "absent" for check in proposition_checks
    )
    needs_context = payload.get("needs_context")
    if not isinstance(needs_context, bool):
        raise ValueError("priority needs_context must be boolean")
    return {
        **payload,
        "blind_item_id": blind_item_id,
        "proposition_checks": [check.to_dict() for check in proposition_checks],
        "relation": relation,
        "source_scope_conflict": source_scope_conflict,
        "needs_context": needs_context,
        "notes": required_string(payload, "notes"),
    }


def _packet_propositions(packet: dict[str, Any]) -> tuple[AtomicProposition, ...]:
    raw_propositions = packet.get("atomic_propositions")
    if not isinstance(raw_propositions, list) or not raw_propositions:
        raise ValueError("priority packet atomic_propositions must be a non-empty list")
    propositions: list[AtomicProposition] = []
    for raw in raw_propositions:
        if not isinstance(raw, dict) or tuple(raw) != ("proposition_id", "text"):
            raise ValueError("priority packet proposition field contract is invalid")
        propositions.append(
            AtomicProposition(
                proposition_id=required_string(raw, "proposition_id"),
                text=required_string(raw, "text"),
            )
        )
    return tuple(propositions)


def _final_label(key: tuple[str, str, str, str], relation: str) -> dict[str, str]:
    return {
        **_canonical_row(key),
        "relation": relation,
    }


def _canonical_key(payload: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        required_string(payload, "task_id"),
        required_string(payload, "target_type"),
        required_string(payload, "target_id"),
        required_string(payload, "source_id"),
    )


def _canonical_row(key: tuple[str, str, str, str]) -> dict[str, str]:
    return {
        "task_id": key[0],
        "target_type": key[1],
        "target_id": key[2],
        "source_id": key[3],
    }


def _unique_rows(
    rows: list[dict[str, Any]],
    key_field: str,
    label: str,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = required_string(row, key_field)
        if key in result:
            raise ValueError(f"duplicate {label} ID: {key}")
        result[key] = row
    return result


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"JSONL rows must be objects: {path}")
        rows.append(payload)
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
