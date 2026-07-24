"""Finalize Phase B source-scope labels with a terminal priority subagent."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from benchmarks.knowledge_state_search.phase_b_source_scope_annotation import (
    DEFAULT_OUTPUT_DIRECTORY,
    EXPECTED_FULL_SOURCE_COUNT,
    scope_row_key,
)
from benchmarks.knowledge_state_search.phase_b_source_scope_annotation_contract import (
    TASK_SCOPE_LABEL_SET,
    required_string,
)

DEFAULT_CONSENSUS_PATH = DEFAULT_OUTPUT_DIRECTORY / "dual_model_scope_consensus.jsonl"
DEFAULT_ACTION_MANIFEST_PATH = DEFAULT_OUTPUT_DIRECTORY / "priority_action_manifest.json"
DEFAULT_ACTION_MAP_PATH = DEFAULT_OUTPUT_DIRECTORY / "data_lead_priority_action_map.jsonl"
DEFAULT_PRIORITY_RESULTS_PATH = DEFAULT_OUTPUT_DIRECTORY / "priority_subagent_results.jsonl"
DEFAULT_OUTPUT_REPORT_PATH = DEFAULT_OUTPUT_DIRECTORY / "priority_adjudication_report.json"
DEFAULT_FINAL_LABELS_PATH = DEFAULT_OUTPUT_DIRECTORY / "model_proxy_source_scope_labels.jsonl"
DEFAULT_UNRESOLVED_PATH = DEFAULT_OUTPUT_DIRECTORY / "priority_unresolved_queue.jsonl"

PRIORITY_REVIEWER_ID = "model:codex-priority-subagent"
PRIORITY_RESULT_FIELDS = (
    "blind_item_id",
    "task_scope",
    "needs_context",
    "notes",
    "reviewer_kind",
    "reviewer_id",
    "model",
)
FINAL_LABEL_FIELDS = (
    "task_id",
    "source_id",
    "task_scope",
)


def finalize_priority_source_scope_annotation(
    *,
    consensus_path: Path = DEFAULT_CONSENSUS_PATH,
    action_manifest_path: Path = DEFAULT_ACTION_MANIFEST_PATH,
    action_map_path: Path = DEFAULT_ACTION_MAP_PATH,
    priority_results_path: Path = DEFAULT_PRIORITY_RESULTS_PATH,
    output_report_path: Path = DEFAULT_OUTPUT_REPORT_PATH,
    final_labels_path: Path = DEFAULT_FINAL_LABELS_PATH,
    unresolved_path: Path = DEFAULT_UNRESOLVED_PATH,
) -> dict[str, object]:
    """Apply terminal priority scope decisions and retain context uncertainty."""

    consensus_rows = _read_jsonl(consensus_path)
    if len(consensus_rows) > EXPECTED_FULL_SOURCE_COUNT:
        raise ValueError("source-scope consensus exceeds the frozen 144-item universe")
    action_manifest = json.loads(action_manifest_path.read_text(encoding="utf-8"))
    action_rows = _read_jsonl(action_map_path)
    result_rows = _read_jsonl(priority_results_path)
    if action_manifest.get("priority_rule") != "subagent_decision_is_terminal":
        raise ValueError("priority action manifest lacks the terminal-decision rule")
    if action_manifest.get("no_recursive_model_review") is not True:
        raise ValueError("priority action manifest must close recursive model review")
    if int(action_manifest.get("action_count", -1)) != len(action_rows):
        raise ValueError("priority action manifest count does not match the private map")

    action_by_blind_id = _unique_rows(
        action_rows,
        "priority_blind_item_id",
        "priority action",
    )
    result_by_blind_id = _unique_rows(
        result_rows,
        "blind_item_id",
        "priority result",
    )
    if set(result_by_blind_id) != set(action_by_blind_id):
        raise ValueError(
            "priority result coverage mismatch: "
            f"missing={sorted(set(action_by_blind_id) - set(result_by_blind_id))}, "
            f"extra={sorted(set(result_by_blind_id) - set(action_by_blind_id))}"
        )
    validated_results = {
        blind_item_id: validate_priority_source_scope_result(result)
        for blind_item_id, result in result_by_blind_id.items()
    }

    action_by_key: dict[
        tuple[str, str],
        tuple[dict[str, Any], dict[str, Any]],
    ] = {}
    for blind_item_id, action in action_by_blind_id.items():
        key = scope_row_key(action)
        if key in action_by_key:
            raise ValueError(f"priority action map duplicates a source-task item: {key}")
        action_by_key[key] = (
            action,
            validated_results[blind_item_id],
        )

    final_labels: list[dict[str, str]] = []
    unresolved: list[dict[str, object]] = []
    priority_flip_count = 0
    priority_spot_check_flip_count = 0
    priority_adjudication_count = 0
    priority_spot_check_count = 0
    seen_keys: set[tuple[str, str]] = set()
    for row in consensus_rows:
        key = scope_row_key(row)
        if key in seen_keys:
            raise ValueError(f"dual-model consensus duplicates a source-task item: {key}")
        seen_keys.add(key)
        action_result = action_by_key.get(key)
        if action_result is None:
            if row.get("disposition") != "dual_model_consensus":
                raise ValueError(f"unrouted non-consensus source-scope item: {key}")
            task_scope = required_string(row, "consensus_task_scope")
            if task_scope not in TASK_SCOPE_LABEL_SET:
                raise ValueError(f"invalid consensus task_scope: {key}")
            final_labels.append(_final_label(key, task_scope))
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
                    "task_id": key[0],
                    "source_id": key[1],
                    "action_type": action_type,
                    "priority_task_scope": result["task_scope"],
                    "priority_notes": result["notes"],
                    "reason": "priority_subagent_needs_context",
                    "repair_required": True,
                }
            )
            continue
        task_scope = str(result["task_scope"])
        consensus_task_scope = row.get("consensus_task_scope")
        if isinstance(consensus_task_scope, str) and consensus_task_scope != task_scope:
            priority_flip_count += 1
            if action_type == "spot_check":
                priority_spot_check_flip_count += 1
        final_labels.append(_final_label(key, task_scope))

    if set(action_by_key) - seen_keys:
        raise ValueError("priority action map references unknown consensus items")
    final_labels.sort(key=lambda row: (row["task_id"], row["source_id"]))
    unresolved.sort(key=lambda row: (str(row["task_id"]), str(row["source_id"])))
    if any(tuple(row) != FINAL_LABEL_FIELDS for row in final_labels):
        raise ValueError("final source-scope label field contract is invalid")
    _write_jsonl(final_labels_path, final_labels)
    _write_jsonl(unresolved_path, unresolved)

    selected_source_count = len(consensus_rows)
    selected_sources_finalized = len(final_labels) == selected_source_count
    full_model_proxy_annotation_complete = (
        selected_source_count == EXPECTED_FULL_SOURCE_COUNT and len(final_labels) == EXPECTED_FULL_SOURCE_COUNT
    )
    report = {
        "status": (
            "model_proxy_source_scope_annotation_complete"
            if full_model_proxy_annotation_complete
            else (
                "selected_model_proxy_source_scope_annotation_complete"
                if selected_sources_finalized
                else "priority_context_repair_required"
            )
        ),
        "annotation_basis": "dual_model_consensus_plus_priority_subagent",
        "model_only_proxy": True,
        "human_verified_count": 0,
        "priority_reviewer_kind": "subagent_model",
        "priority_reviewer_id": PRIORITY_REVIEWER_ID,
        "priority_decision_is_terminal": True,
        "no_recursive_model_review": True,
        "expected_full_source_count": EXPECTED_FULL_SOURCE_COUNT,
        "selected_source_task_count": selected_source_count,
        "priority_action_count": len(action_rows),
        "priority_adjudication_count": priority_adjudication_count,
        "priority_spot_check_count": priority_spot_check_count,
        "priority_flip_count": priority_flip_count,
        "priority_spot_check_flip_count": priority_spot_check_flip_count,
        "unresolved_context_count": len(unresolved),
        "model_proxy_labels_finalized": len(final_labels),
        "selected_sources_finalized": selected_sources_finalized,
        "full_model_proxy_annotation_complete": full_model_proxy_annotation_complete,
        "dataset_frozen": False,
        "method_runs_authorized": False,
    }
    output_report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def validate_priority_source_scope_result(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Validate exact terminal priority result fields and model identity."""

    if set(payload) != set(PRIORITY_RESULT_FIELDS):
        raise ValueError("priority source-scope result field contract is invalid")
    if payload.get("reviewer_kind") != "subagent_model":
        raise ValueError("priority reviewer_kind must be subagent_model")
    if payload.get("reviewer_id") != PRIORITY_REVIEWER_ID:
        raise ValueError("priority reviewer_id is invalid")
    task_scope = required_string(payload, "task_scope")
    if task_scope not in TASK_SCOPE_LABEL_SET:
        raise ValueError(f"priority task_scope is invalid: {task_scope}")
    needs_context = payload.get("needs_context")
    if not isinstance(needs_context, bool):
        raise ValueError("priority needs_context must be boolean")
    return {
        **payload,
        "blind_item_id": required_string(payload, "blind_item_id"),
        "task_scope": task_scope,
        "needs_context": needs_context,
        "notes": required_string(payload, "notes"),
        "model": required_string(payload, "model"),
    }


def build_parser() -> argparse.ArgumentParser:
    """Build the terminal source-scope finalizer CLI."""

    parser = argparse.ArgumentParser(description="Finalize Phase B model-proxy source-scope labels.")
    parser.add_argument("--consensus", type=Path, default=DEFAULT_CONSENSUS_PATH)
    parser.add_argument(
        "--action-manifest",
        type=Path,
        default=DEFAULT_ACTION_MANIFEST_PATH,
    )
    parser.add_argument("--action-map", type=Path, default=DEFAULT_ACTION_MAP_PATH)
    parser.add_argument("--results", type=Path, default=DEFAULT_PRIORITY_RESULTS_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_REPORT_PATH)
    parser.add_argument("--final-labels", type=Path, default=DEFAULT_FINAL_LABELS_PATH)
    parser.add_argument("--unresolved", type=Path, default=DEFAULT_UNRESOLVED_PATH)
    return parser


def main() -> int:
    """Validate priority results and print the terminal model-only report."""

    args = build_parser().parse_args()
    report = finalize_priority_source_scope_annotation(
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


def _final_label(key: tuple[str, str], task_scope: str) -> dict[str, str]:
    return {
        "task_id": key[0],
        "source_id": key[1],
        "task_scope": task_scope,
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
