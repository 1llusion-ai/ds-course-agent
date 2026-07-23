"""Validate and report whether a Phase B dataset is ready to be frozen."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from benchmarks.knowledge_state_search.confirmatory_schema import (
    ClaimKind,
    ConfirmatorySchema,
)

DEFAULT_DATASET = Path("benchmarks/data/knowledge_state_search_confirmatory_v3")
DEFAULT_OUTPUT = Path("var/artifacts/knowledge_state_search/phase_b_freeze_report.json")


def build_phase_b_freeze_report(schema: ConfirmatorySchema) -> dict[str, Any]:
    """Return the immutable dataset facts after all Phase B gates pass."""

    schema.validate_phase_b_contract()
    learner_kinds = Counter(
        claim.kind.value
        for task in schema.tasks
        for claim in schema.claims_for_task(task.task_id)
        if claim.kind is not ClaimKind.CORE
    )
    path_ids = {path_id for edge in schema.edges if edge.required for path_id in edge.path_ids}
    return {
        "schema_version": 1,
        "audit": "knowledge_state_search_phase_b_freeze",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass",
        "benchmark_id": schema.manifest.benchmark_id,
        "counts": {
            "tasks": len(schema.tasks),
            "profiles": len(schema.profiles),
            "claims": len(schema.claims),
            "edges": len(schema.edges),
            "required_paths": len(path_ids),
            "sources": len(schema.sources),
            "annotations": len(schema.annotations),
        },
        "learner_gap_types": dict(sorted(learner_kinds.items())),
        "splits": {split.name: list(split.task_ids) for split in schema.splits},
        "annotation_audit": {
            "status": schema.annotation_audit.status,
            "annotators": list(schema.annotation_audit.annotators),
            "adjudicated": schema.annotation_audit.adjudicated,
            "independently_judged_pairs": schema.annotation_audit.independently_judged_pairs,
        },
        "method_runs_authorized": False,
        "next_gate": "deterministic_gold_vs_core_discriminability",
    }


def run_phase_b_freeze_check(dataset: Path) -> dict[str, Any]:
    """Load a candidate dataset and return a pass/fail report."""

    try:
        return build_phase_b_freeze_report(ConfirmatorySchema.load(dataset))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "schema_version": 1,
            "audit": "knowledge_state_search_phase_b_freeze",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "fail",
            "dataset": str(dataset),
            "error": str(exc),
            "method_runs_authorized": False,
        }


def build_parser() -> argparse.ArgumentParser:
    """Build the Phase B freeze-check command-line interface."""

    parser = argparse.ArgumentParser(description="Validate the frozen Phase B dataset contract.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main() -> int:
    """Run the Phase B freeze check and persist its report."""

    args = build_parser().parse_args()
    report = run_phase_b_freeze_check(args.dataset)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
