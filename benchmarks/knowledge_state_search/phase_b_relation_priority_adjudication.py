"""Finalize model-proxy relation labels with the priority subagent."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from benchmarks.knowledge_state_search.phase_b_relation_annotation import (
    DEFAULT_OUTPUT_DIRECTORY,
)
from benchmarks.knowledge_state_search.phase_b_relation_annotation_contract import (
    RELATION_LABEL_SET,
    required_string,
)

DEFAULT_CONSENSUS_PATH = DEFAULT_OUTPUT_DIRECTORY / "dual_model_consensus.jsonl"
DEFAULT_ACTION_MANIFEST_PATH = DEFAULT_OUTPUT_DIRECTORY / "priority_action_manifest.json"
DEFAULT_ACTION_MAP_PATH = DEFAULT_OUTPUT_DIRECTORY / "data_lead_priority_action_map.jsonl"
DEFAULT_PRIORITY_RESULTS_PATH = DEFAULT_OUTPUT_DIRECTORY / "priority_subagent_results.jsonl"
DEFAULT_OUTPUT_REPORT_PATH = DEFAULT_OUTPUT_DIRECTORY / "priority_adjudication_report.json"
DEFAULT_FINAL_LABELS_PATH = DEFAULT_OUTPUT_DIRECTORY / "model_proxy_annotations.jsonl"
DEFAULT_UNRESOLVED_PATH = DEFAULT_OUTPUT_DIRECTORY / "priority_unresolved_queue.jsonl"
_PRIORITY_REVIEWER_ID = "model:codex-priority-subagent"
_RESULT_FIELDS = (
    "blind_item_id",
    "relation",
    "needs_context",
    "notes",
    "reviewer_kind",
    "reviewer_id",
    "model",
)


def finalize_priority_relation_adjudication(
    *,
    consensus_path: Path = DEFAULT_CONSENSUS_PATH,
    action_manifest_path: Path = DEFAULT_ACTION_MANIFEST_PATH,
    action_map_path: Path = DEFAULT_ACTION_MAP_PATH,
    priority_results_path: Path = DEFAULT_PRIORITY_RESULTS_PATH,
    output_report_path: Path = DEFAULT_OUTPUT_REPORT_PATH,
    final_labels_path: Path = DEFAULT_FINAL_LABELS_PATH,
    unresolved_path: Path = DEFAULT_UNRESOLVED_PATH,
) -> dict[str, object]:
    """Apply terminal priority decisions without claiming human annotation."""

    consensus_rows = _read_jsonl(consensus_path)
    action_manifest = json.loads(action_manifest_path.read_text(encoding="utf-8"))
    action_rows = _read_jsonl(action_map_path)
    result_rows = _read_jsonl(priority_results_path)
    if action_manifest.get("priority_rule") != "subagent_decision_is_terminal":
        raise ValueError("priority action manifest lacks the terminal-decision rule")
    if action_manifest.get("no_recursive_model_review") is not True:
        raise ValueError("priority action manifest must close recursive model review")
    if int(action_manifest.get("action_count", -1)) != len(action_rows):
        raise ValueError("priority action manifest count does not match the private map")

    action_by_blind_id = _unique_rows(action_rows, "priority_blind_item_id", "priority action")
    result_by_blind_id = _unique_rows(result_rows, "blind_item_id", "priority result")
    if set(result_by_blind_id) != set(action_by_blind_id):
        raise ValueError(
            "priority result coverage mismatch: "
            f"missing={sorted(set(action_by_blind_id) - set(result_by_blind_id))}, "
            f"extra={sorted(set(result_by_blind_id) - set(action_by_blind_id))}"
        )
    validated_results = {
        blind_item_id: _validate_priority_result(result) for blind_item_id, result in result_by_blind_id.items()
    }

    action_by_key: dict[tuple[str, str, str, str], tuple[dict[str, Any], dict[str, Any]]] = {}
    for blind_item_id, action in action_by_blind_id.items():
        key = _canonical_key(action)
        if key in action_by_key:
            raise ValueError(f"priority action map duplicates a canonical pair: {key}")
        action_by_key[key] = (action, validated_results[blind_item_id])

    final_labels: list[dict[str, str]] = []
    unresolved: list[dict[str, object]] = []
    priority_flip_count = 0
    priority_spot_check_flip_count = 0
    priority_adjudication_count = 0
    priority_spot_check_count = 0
    seen_keys: set[tuple[str, str, str, str]] = set()
    for row in consensus_rows:
        key = _canonical_key(row)
        if key in seen_keys:
            raise ValueError(f"dual-model consensus duplicates a canonical pair: {key}")
        seen_keys.add(key)
        action_result = action_by_key.get(key)
        if action_result is None:
            if row.get("disposition") != "dual_model_consensus":
                raise ValueError(f"unrouted non-consensus relation pair: {key}")
            relation = required_string(row, "consensus_relation")
            if relation not in RELATION_LABEL_SET:
                raise ValueError(f"invalid consensus relation: {key}")
            final_labels.append(_final_label(key, relation))
            continue

        action, result = action_result
        action_type = required_string(action, "action_type")
        if action_type == "adjudication":
            priority_adjudication_count += 1
        elif action_type == "spot_check":
            priority_spot_check_count += 1
        else:
            raise ValueError(f"invalid priority action_type: {action_type}")
        if result["needs_context"] is True:
            unresolved.append(
                {
                    **_canonical_row(key),
                    "action_type": action_type,
                    "priority_relation": result["relation"],
                    "priority_notes": result["notes"],
                    "reason": "priority_subagent_needs_context",
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
                "selected_model_proxy_annotation_complete"
                if selected_pairs_finalized
                else "priority_context_repair_required"
            )
        ),
        "annotation_basis": "dual_model_consensus_plus_priority_subagent",
        "model_only_proxy": True,
        "human_verified_count": 0,
        "priority_reviewer_kind": "subagent_model",
        "priority_reviewer_id": _PRIORITY_REVIEWER_ID,
        "priority_decision_is_terminal": True,
        "no_recursive_model_review": True,
        "selected_canonical_pair_count": selected_pair_count,
        "priority_action_count": len(action_rows),
        "priority_adjudication_count": priority_adjudication_count,
        "priority_spot_check_count": priority_spot_check_count,
        "priority_flip_count": priority_flip_count,
        "priority_spot_check_flip_count": priority_spot_check_flip_count,
        "unresolved_context_count": len(unresolved),
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
    parser.add_argument("--action-manifest", type=Path, default=DEFAULT_ACTION_MANIFEST_PATH)
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
        action_manifest_path=args.action_manifest,
        action_map_path=args.action_map,
        priority_results_path=args.results,
        output_report_path=args.output,
        final_labels_path=args.final_labels,
        unresolved_path=args.unresolved,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _validate_priority_result(payload: dict[str, Any]) -> dict[str, Any]:
    if tuple(payload) != _RESULT_FIELDS:
        raise ValueError("priority result field contract is invalid")
    if payload.get("reviewer_kind") != "subagent_model":
        raise ValueError("priority reviewer_kind must be subagent_model")
    if payload.get("reviewer_id") != _PRIORITY_REVIEWER_ID:
        raise ValueError("priority reviewer_id is invalid")
    required_string(payload, "model")
    relation = required_string(payload, "relation")
    if relation not in RELATION_LABEL_SET:
        raise ValueError(f"priority relation is invalid: {relation}")
    needs_context = payload.get("needs_context")
    if not isinstance(needs_context, bool):
        raise ValueError("priority needs_context must be boolean")
    return {
        **payload,
        "blind_item_id": required_string(payload, "blind_item_id"),
        "relation": relation,
        "needs_context": needs_context,
        "notes": required_string(payload, "notes"),
    }


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
