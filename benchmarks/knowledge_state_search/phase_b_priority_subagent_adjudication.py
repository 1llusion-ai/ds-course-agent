"""Finalize source verification using the owner-authorized priority subagent."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from benchmarks.knowledge_state_search.phase_b_model_verification import (
    DEFAULT_OUTPUT_DIRECTORY,
)
from benchmarks.knowledge_state_search.phase_b_model_verification_contract import (
    required_string,
)

DEFAULT_ACTION_PACKET = DEFAULT_OUTPUT_DIRECTORY / "human_review_action_packet.jsonl"
DEFAULT_SUBAGENT_RESULTS = DEFAULT_OUTPUT_DIRECTORY / "subagent_review_results.jsonl"
DEFAULT_SUBAGENT_SUMMARY = DEFAULT_OUTPUT_DIRECTORY / "subagent_review_summary.json"
DEFAULT_VERIFICATION_REPORT = DEFAULT_OUTPUT_DIRECTORY / "verification_report.json"
DEFAULT_OUTPUT_REPORT = DEFAULT_OUTPUT_DIRECTORY / "priority_subagent_adjudication_report.json"
_ALLOWED_STATUSES = frozenset(
    {
        "verified",
        "repair_needed",
        "inaccessible",
        "needs_context",
        "access_unresolved",
    }
)


def validate_priority_subagent_adjudication(
    *,
    action_packet_path: Path = DEFAULT_ACTION_PACKET,
    subagent_results_path: Path = DEFAULT_SUBAGENT_RESULTS,
    subagent_summary_path: Path = DEFAULT_SUBAGENT_SUMMARY,
    verification_report_path: Path = DEFAULT_VERIFICATION_REPORT,
) -> dict[str, object]:
    """Validate exact priority-review coverage and compute the model-only gate."""

    actions = _load_unique_rows(action_packet_path, "action")
    results = _load_unique_rows(subagent_results_path, "subagent result")
    expected_ids = set(actions)
    if set(results) != expected_ids:
        raise ValueError(
            "priority subagent coverage mismatch: "
            f"missing={sorted(expected_ids - set(results))}, "
            f"extra={sorted(set(results) - expected_ids)}"
        )

    status_by_source: dict[str, str] = {}
    for source_id in sorted(expected_ids):
        action = actions[source_id]
        result = results[source_id]
        if result.get("action_id") != action.get("action_id"):
            raise ValueError(f"priority subagent action_id mismatch: {source_id}")
        if result.get("action_type") != action.get("action_type"):
            raise ValueError(f"priority subagent action_type mismatch: {source_id}")
        if result.get("reviewer_kind") != "subagent_model":
            raise ValueError(f"priority reviewer_kind is invalid: {source_id}")
        if result.get("reviewer_id") != "model:codex-subagent":
            raise ValueError(f"priority reviewer_id is invalid: {source_id}")
        status = required_string(result, "status")
        if status not in _ALLOWED_STATUSES:
            raise ValueError(f"priority subagent status is invalid: {source_id}")
        evidence = result.get("evidence")
        if not isinstance(evidence, dict) or not evidence:
            raise ValueError(f"priority subagent evidence is missing: {source_id}")
        required_string(result, "notes")
        status_by_source[source_id] = status

    verification_report = json.loads(verification_report_path.read_text(encoding="utf-8"))
    disposition_counts = verification_report.get("disposition_counts")
    if not isinstance(disposition_counts, dict):
        raise ValueError("verification report lacks disposition_counts")
    if int(verification_report.get("human_review_action_count", -1)) != len(actions):
        raise ValueError("verification report action count does not match packet")
    if int(disposition_counts.get("repair_required", -1)) != 0:
        raise ValueError("priority adjudication cannot bypass a joint repair requirement")

    summary = json.loads(subagent_summary_path.read_text(encoding="utf-8"))
    if int(summary.get("review_count", -1)) != len(results):
        raise ValueError("subagent summary review_count does not match results")
    if summary.get("human_verified_count") != 0:
        raise ValueError("subagent summary must not claim human verification")
    if summary.get("final_decision") is not True:
        raise ValueError("subagent summary must mark the decision as final")
    if summary.get("no_further_model_review_required") is not True:
        raise ValueError("subagent summary must close recursive model review")

    adjudication_ids = {
        source_id for source_id, action in actions.items() if action.get("action_type") == "adjudication"
    }
    spot_check_ids = {source_id for source_id, action in actions.items() if action.get("action_type") == "spot_check"}
    nonverified_ids = sorted(source_id for source_id, status in status_by_source.items() if status != "verified")
    adjudication_verified_count = sum(status_by_source[source_id] == "verified" for source_id in adjudication_ids)
    consensus_verified_count = int(disposition_counts.get("model_consensus_verified", -1))
    source_count = int(verification_report.get("source_count", -1))
    final_verified_count = consensus_verified_count + adjudication_verified_count
    source_gate_complete = not nonverified_ids and final_verified_count == source_count
    return {
        "status": "pass" if source_gate_complete else "priority_review_gate_failed",
        "final_decision": True,
        "no_further_model_review_required": True,
        "decision_authority": "dataset_owner_authorized_priority_subagent",
        "verification_basis": "dual_model_plus_priority_subagent",
        "source_count": source_count,
        "model_consensus_verified_count": consensus_verified_count,
        "priority_action_count": len(actions),
        "priority_adjudication_count": len(adjudication_ids),
        "priority_spot_check_count": len(spot_check_ids),
        "priority_verified_count": len(results) - len(nonverified_ids),
        "priority_nonverified_source_ids": nonverified_ids,
        "final_source_verified_count": final_verified_count,
        "human_verified_count": 0,
        "source_verification_gate_complete": source_gate_complete,
        "blind_annotation_authorized": source_gate_complete,
        "annotation_started": False,
        "dataset_frozen": False,
        "method_runs_authorized": False,
    }


def write_priority_subagent_adjudication_report(
    *,
    action_packet_path: Path = DEFAULT_ACTION_PACKET,
    subagent_results_path: Path = DEFAULT_SUBAGENT_RESULTS,
    subagent_summary_path: Path = DEFAULT_SUBAGENT_SUMMARY,
    verification_report_path: Path = DEFAULT_VERIFICATION_REPORT,
    output_path: Path = DEFAULT_OUTPUT_REPORT,
) -> dict[str, object]:
    """Validate the priority decision and persist its explicit model-only state."""

    report = validate_priority_subagent_adjudication(
        action_packet_path=action_packet_path,
        subagent_results_path=subagent_results_path,
        subagent_summary_path=subagent_summary_path,
        verification_report_path=verification_report_path,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def build_parser() -> argparse.ArgumentParser:
    """Build the owner-authorized priority adjudication CLI."""

    parser = argparse.ArgumentParser(description="Finalize Phase B source verification with the priority subagent.")
    parser.add_argument("--actions", type=Path, default=DEFAULT_ACTION_PACKET)
    parser.add_argument("--results", type=Path, default=DEFAULT_SUBAGENT_RESULTS)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUBAGENT_SUMMARY)
    parser.add_argument(
        "--verification-report",
        type=Path,
        default=DEFAULT_VERIFICATION_REPORT,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_REPORT)
    return parser


def main() -> int:
    """Validate and print the priority subagent source-gate report."""

    args = build_parser().parse_args()
    report = write_priority_subagent_adjudication_report(
        action_packet_path=args.actions,
        subagent_results_path=args.results,
        subagent_summary_path=args.summary,
        verification_report_path=args.verification_report,
        output_path=args.output,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _load_unique_rows(path: Path, label: str) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for payload in _read_jsonl(path):
        source_id = required_string(payload, "source_id")
        if source_id in rows:
            raise ValueError(f"duplicate {label} source_id: {source_id}")
        rows[source_id] = payload
    if not rows:
        raise ValueError(f"{label} file must not be empty")
    return rows


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
