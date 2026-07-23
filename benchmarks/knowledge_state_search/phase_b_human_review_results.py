"""Validate real human follow-up results for Phase B dual-model verification."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from benchmarks.knowledge_state_search.phase_b_model_verification import (
    DEFAULT_OUTPUT_DIRECTORY,
)
from benchmarks.knowledge_state_search.phase_b_model_verification_contract import (
    required_string,
)

DEFAULT_ACTION_PACKET = DEFAULT_OUTPUT_DIRECTORY / "human_review_action_packet.jsonl"
DEFAULT_VERIFICATION_REPORT = DEFAULT_OUTPUT_DIRECTORY / "verification_report.json"
DEFAULT_OUTPUT_REPORT = DEFAULT_OUTPUT_DIRECTORY / "human_review_result_validation_report.json"
_RESERVED_REVIEWER_IDS = frozenset(
    {
        "agent",
        "doubao",
        "mimo",
        "model",
        "human-reviewer-id",
    }
)


class HumanReviewStatus(str, Enum):
    """Allowed real-human review outcomes."""

    VERIFIED = "verified"
    REPAIR_NEEDED = "repair_needed"
    INACCESSIBLE = "inaccessible"
    NEEDS_CONTEXT = "needs_context"


class HumanActionType(str, Enum):
    """Reason a source was routed to a real human."""

    ADJUDICATION = "adjudication"
    SPOT_CHECK = "spot_check"


@dataclass(frozen=True)
class HumanReviewResult:
    """One validated result produced by a real human reviewer."""

    source_id: str
    status: HumanReviewStatus
    reviewer_id: str
    reviewed_at: str
    notes: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> HumanReviewResult:
        """Parse one result and reject model or placeholder reviewer identities."""

        source_id = required_string(payload, "source_id")
        status = HumanReviewStatus(required_string(payload, "status"))
        reviewer_id = required_string(payload, "reviewer_id")
        normalized_reviewer = reviewer_id.casefold()
        if (
            normalized_reviewer in _RESERVED_REVIEWER_IDS
            or normalized_reviewer.startswith("agent:")
            or normalized_reviewer.startswith("model:")
        ):
            raise ValueError(f"reviewer_id is not a real human identity: {reviewer_id}")
        reviewed_at = required_string(payload, "reviewed_at")
        _validate_aware_timestamp(reviewed_at, source_id=source_id)
        notes = payload.get("notes", "")
        if not isinstance(notes, str):
            raise ValueError(f"notes must be a string: {source_id}")
        return cls(
            source_id=source_id,
            status=status,
            reviewer_id=reviewer_id,
            reviewed_at=reviewed_at,
            notes=notes.strip(),
        )


def validate_human_review_results(
    results_path: Path,
    *,
    action_packet_path: Path = DEFAULT_ACTION_PACKET,
    verification_report_path: Path = DEFAULT_VERIFICATION_REPORT,
) -> dict[str, object]:
    """Validate exact human-action coverage and compute the source gate state."""

    actions = _load_actions(action_packet_path)
    results = _load_results(results_path)
    expected_ids = set(actions)
    result_ids = set(results)
    if result_ids != expected_ids:
        raise ValueError(
            "human review result coverage mismatch: "
            f"missing={sorted(expected_ids - result_ids)}, "
            f"extra={sorted(result_ids - expected_ids)}"
        )

    verification_report = json.loads(verification_report_path.read_text(encoding="utf-8"))
    disposition_counts = verification_report.get("disposition_counts")
    if not isinstance(disposition_counts, dict):
        raise ValueError("verification report lacks disposition_counts")
    consensus_verified_count = int(disposition_counts.get("model_consensus_verified", -1))
    if int(verification_report.get("human_review_action_count", -1)) != len(actions):
        raise ValueError("verification report human-action count does not match packet")

    adjudication_ids = {
        source_id for source_id, action_type in actions.items() if action_type is HumanActionType.ADJUDICATION
    }
    spot_check_ids = {
        source_id for source_id, action_type in actions.items() if action_type is HumanActionType.SPOT_CHECK
    }
    adjudication_nonverified = sorted(
        source_id for source_id in adjudication_ids if results[source_id].status is not HumanReviewStatus.VERIFIED
    )
    spot_check_nonverified = sorted(
        source_id for source_id in spot_check_ids if results[source_id].status is not HumanReviewStatus.VERIFIED
    )
    source_gate_complete = not adjudication_nonverified and not spot_check_nonverified
    adjudication_verified_count = len(adjudication_ids) - len(adjudication_nonverified)
    return {
        "status": "pass" if source_gate_complete else "valid_results_gate_failed",
        "result_count": len(results),
        "expected_result_count": len(actions),
        "unique_reviewer_count": len({result.reviewer_id for result in results.values()}),
        "adjudication_count": len(adjudication_ids),
        "adjudication_verified_count": adjudication_verified_count,
        "adjudication_nonverified_source_ids": adjudication_nonverified,
        "spot_check_count": len(spot_check_ids),
        "spot_check_verified_count": len(spot_check_ids) - len(spot_check_nonverified),
        "spot_check_nonverified_source_ids": spot_check_nonverified,
        "full_consensus_reaudit_required": bool(spot_check_nonverified),
        "model_consensus_verified_count": consensus_verified_count,
        "final_source_verified_count": (consensus_verified_count + adjudication_verified_count),
        "source_verification_gate_complete": source_gate_complete,
        "blind_annotation_authorized": source_gate_complete,
        "annotation_started": False,
        "dataset_frozen": False,
        "method_runs_authorized": False,
    }


def write_human_review_result_report(
    results_path: Path,
    *,
    action_packet_path: Path = DEFAULT_ACTION_PACKET,
    verification_report_path: Path = DEFAULT_VERIFICATION_REPORT,
    output_path: Path = DEFAULT_OUTPUT_REPORT,
) -> dict[str, object]:
    """Validate real results and persist a gate report without changing labels."""

    report = validate_human_review_results(
        results_path,
        action_packet_path=action_packet_path,
        verification_report_path=verification_report_path,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def build_parser() -> argparse.ArgumentParser:
    """Build the human-result ingestion CLI."""

    parser = argparse.ArgumentParser(description="Validate real human follow-up results for Phase B sources.")
    parser.add_argument("results", type=Path)
    parser.add_argument("--actions", type=Path, default=DEFAULT_ACTION_PACKET)
    parser.add_argument(
        "--verification-report",
        type=Path,
        default=DEFAULT_VERIFICATION_REPORT,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_REPORT)
    return parser


def main() -> int:
    """Validate one supplied human result file and print the gate report."""

    args = build_parser().parse_args()
    report = write_human_review_result_report(
        args.results,
        action_packet_path=args.actions,
        verification_report_path=args.verification_report,
        output_path=args.output,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _load_actions(path: Path) -> dict[str, HumanActionType]:
    actions: dict[str, HumanActionType] = {}
    for payload in _read_jsonl(path):
        source_id = required_string(payload, "source_id")
        if source_id in actions:
            raise ValueError(f"duplicate human action source_id: {source_id}")
        action_type = HumanActionType(required_string(payload, "action_type"))
        expected_action_id = f"human_{action_type.value}:{source_id}"
        if payload.get("action_id") != expected_action_id:
            raise ValueError(f"human action_id is invalid: {source_id}")
        actions[source_id] = action_type
    if not actions:
        raise ValueError("human action packet must not be empty")
    return actions


def _load_results(path: Path) -> dict[str, HumanReviewResult]:
    results: dict[str, HumanReviewResult] = {}
    for payload in _read_jsonl(path):
        result = HumanReviewResult.from_dict(payload)
        if result.source_id in results:
            raise ValueError(f"duplicate human review source_id: {result.source_id}")
        results[result.source_id] = result
    return results


def _validate_aware_timestamp(value: str, *, source_id: str) -> None:
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        timestamp = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"reviewed_at is not ISO-8601: {source_id}") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError(f"reviewed_at must include a timezone: {source_id}")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
