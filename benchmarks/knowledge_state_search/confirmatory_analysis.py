"""Analyze paired M1/M3 results from the v2 confirmatory experiment."""

from __future__ import annotations

import argparse
import copy
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from benchmarks.knowledge_state_search.evidence import EvidenceSnapshot
from benchmarks.knowledge_state_search.ledger import ClaimLevelEvaluator
from benchmarks.knowledge_state_search.models import EvidenceRequirement


def analyze_confirmatory(
    payload: dict[str, Any],
    *,
    source_artifact: str,
    snapshot: EvidenceSnapshot | None = None,
) -> dict[str, Any]:
    """Compute method summaries and paired M3-minus-M1 deltas."""

    if snapshot is not None:
        payload = _replay_metrics(payload, snapshot)
    successful = [item for item in payload["results"] if item.get("error") is None]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in successful:
        grouped[item["method"]].append(item)
    by_case = {
        (item["task_id"], item["student_id"], item.get("repeat", 1), item["method"]): item for item in successful
    }
    paired_cases = []
    for key in sorted(
        {(task_id, student_id, repeat) for task_id, student_id, repeat, method in by_case if method == "M1"}
    ):
        m1 = by_case.get((*key, "M1"))
        m3 = by_case.get((*key, "M3"))
        if m1 is None or m3 is None:
            continue
        m1_metrics = m1["metrics"]
        m3_metrics = m3["metrics"]
        learner_gap = m3["evaluation_gap"]["learner_requirements"]
        paired_cases.append(
            {
                "task_id": key[0],
                "student_id": key[1],
                "repeat": key[2],
                "profile_type": _profile_type(key[1]),
                "learner_requirement_ids": [item["requirement_id"] for item in learner_gap],
                "m1": _metric_view(m1),
                "m3": _metric_view(m3),
                "delta_m3_minus_m1": {
                    field: _delta(m3_metrics.get(field), m1_metrics.get(field))
                    for field in (
                        "hard_core_recall",
                        "learner_recall",
                        "evidence_precision",
                        "strict_supported_rate",
                        "contradicted_rate",
                        "unannotated_rate",
                        "claim_conflict_rate",
                    )
                }
                | {"search_calls": m3["search_calls"] - m1["search_calls"]},
                "m3_visible_learner_obligation_count": len(
                    (m3.get("visible_gap") or {}).get("learner_requirements", [])
                ),
            }
        )
    return {
        "schema_version": 1,
        "analysis": "knowledge_state_search_confirmatory",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_artifact": source_artifact,
        "scope": {
            "tasks": len({item["task_id"] for item in successful}),
            "profiles": len({(item["task_id"], item["student_id"]) for item in successful}),
            "repeats": payload["config"]["repeats"],
            "snapshot": payload["config"]["snapshot_id"],
            "inferential_claims_allowed": False,
        },
        "method_summary": {method: _method_summary(items) for method, items in sorted(grouped.items())},
        "paired_m3_vs_m1": {
            "case_count": len(paired_cases),
            "learner_gap_case_count": sum(bool(item["learner_requirement_ids"]) for item in paired_cases),
            "metrics": {
                field: _paired_summary(paired_cases, field)
                for field in (
                    "hard_core_recall",
                    "learner_recall",
                    "evidence_precision",
                    "strict_supported_rate",
                    "contradicted_rate",
                    "unannotated_rate",
                    "claim_conflict_rate",
                    "search_calls",
                )
            },
            "m3_no_gap_visible_obligation_rate": _no_gap_visible_obligation_rate(paired_cases),
            "cases": paired_cases,
        },
    }


def _metric_view(item: dict[str, Any]) -> dict[str, Any]:
    metrics = item["metrics"]
    return {
        "hard_core_recall": metrics["hard_core_recall"],
        "learner_recall": metrics["learner_recall"],
        "evidence_precision": metrics["evidence_precision"],
        "strict_supported_rate": metrics["strict_supported_rate"],
        "contradicted_rate": metrics["contradicted_rate"],
        "unannotated_rate": metrics["unannotated_rate"],
        "claim_conflict_rate": metrics.get("claim_conflict_rate"),
        "search_calls": item["search_calls"],
        "selected_source_ids": item["selected_source_ids"],
    }


def _method_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = [item["metrics"] for item in items]
    return {
        "cases": len(items),
        "hard_core_recall": _mean(item["hard_core_recall"] for item in metrics),
        "learner_recall_nonempty_gap": _mean(
            item["learner_recall"] for item in metrics if item["learner_recall"] is not None
        ),
        "evidence_precision": _mean(
            item["evidence_precision"] for item in metrics if item["evidence_precision"] is not None
        ),
        "strict_supported_rate": _mean(
            item["strict_supported_rate"] for item in metrics if item["strict_supported_rate"] is not None
        ),
        "contradicted_rate": _mean(
            item["contradicted_rate"] for item in metrics if item["contradicted_rate"] is not None
        ),
        "unannotated_rate": _mean(item["unannotated_rate"] for item in metrics if item["unannotated_rate"] is not None),
        "claim_conflict_rate": _mean(
            item["claim_conflict_rate"] for item in metrics if item.get("claim_conflict_rate") is not None
        ),
        "search_calls": _mean(float(item["search_calls"]) for item in items),
    }


def _paired_summary(cases: list[dict[str, Any]], field: str) -> dict[str, Any]:
    values = [item["delta_m3_minus_m1"][field] for item in cases if item["delta_m3_minus_m1"][field] is not None]
    return {
        "n": len(values),
        "mean_delta": _mean(values),
        "nonnegative_count": sum(value >= 0 for value in values),
        "positive_count": sum(value > 0 for value in values),
        "negative_count": sum(value < 0 for value in values),
    }


def _no_gap_visible_obligation_rate(cases: list[dict[str, Any]]) -> float | None:
    no_gap = [item for item in cases if not item["learner_requirement_ids"]]
    if not no_gap:
        return None
    return sum(item["m3_visible_learner_obligation_count"] > 0 for item in no_gap) / len(no_gap)


def _profile_type(student_id: str) -> str:
    for suffix in ("multi_gap", "misconception_gap", "prereq_gap", "goal_gap", "nogap"):
        if student_id.endswith(suffix):
            return suffix
    return "other"


def _replay_metrics(
    payload: dict[str, Any],
    snapshot: EvidenceSnapshot,
) -> dict[str, Any]:
    """Re-evaluate saved source selections under the current metric contract."""

    replayed = copy.deepcopy(payload)
    evaluator = ClaimLevelEvaluator(snapshot)
    for item in replayed["results"]:
        if item.get("error") is not None:
            continue
        gap = item["evaluation_gap"]
        requirements = tuple(
            EvidenceRequirement.from_dict(requirement)
            for requirement in (*gap["core_requirements"], *gap["learner_requirements"])
        )
        metrics = evaluator.evaluate(
            task_id=item["task_id"],
            requirements=requirements,
            selected_source_ids=item["selected_source_ids"],
        )
        item["metrics"] = {
            "hard_core_recall": metrics.hard_core_recall,
            "learner_recall": metrics.learner_recall,
            "evidence_precision": metrics.evidence_precision,
            "strict_supported_rate": metrics.strict_supported_rate,
            "contradicted_rate": metrics.contradicted_rate,
            "unannotated_rate": metrics.unannotated_rate,
            "claim_conflict_rate": metrics.claim_conflict_rate,
            "assessments": [
                {
                    "requirement_id": assessment.requirement_id,
                    "kind": assessment.kind,
                    "status": assessment.status.value,
                    "conflicted": assessment.conflicted,
                    "source_ids": list(assessment.source_ids),
                }
                for assessment in metrics.assessments
            ],
        }
    return replayed


def _delta(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return left - right


def _mean(values: Any) -> float | None:
    materialized = list(values)
    return mean(materialized) if materialized else None


def build_parser() -> argparse.ArgumentParser:
    """Build the confirmatory analysis CLI."""

    parser = argparse.ArgumentParser(description="Analyze M1/M3 confirmatory results.")
    parser.add_argument("artifact")
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--snapshot",
        help="Replay saved source selections under the current metric contract.",
    )
    return parser


def main() -> int:
    """Analyze one artifact and save a reusable JSON report."""

    args = build_parser().parse_args()
    payload = json.loads(Path(args.artifact).read_text(encoding="utf-8"))
    report = analyze_confirmatory(
        payload,
        source_artifact=args.artifact,
        snapshot=EvidenceSnapshot.load(args.snapshot) if args.snapshot else None,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["method_summary"], ensure_ascii=False, indent=2))
    print(json.dumps(report["paired_m3_vs_m1"]["metrics"], ensure_ascii=False, indent=2))
    print(f"Saved confirmatory analysis to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
