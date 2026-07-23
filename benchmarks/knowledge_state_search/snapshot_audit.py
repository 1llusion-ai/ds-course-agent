"""Audit fixed-snapshot support coverage before running method comparisons."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from benchmarks.knowledge_state_search.controlled_profiles import controlled_profiles
from benchmarks.knowledge_state_search.evidence import EvidenceSnapshot, SupportStatus
from benchmarks.knowledge_state_search.gap_planner import KnowledgeStateGapPlanner
from benchmarks.knowledge_state_search.models import EvidenceRequirement, SearchTask

DEFAULT_TASKS = Path("benchmarks/data/knowledge_state_search_probe_v1.json")
DEFAULT_SNAPSHOT = Path("benchmarks/data/knowledge_state_search_snapshot_v1")
DEFAULT_OUTPUT = Path("var/artifacts/knowledge_state_search/snapshot_coverage_audit_v1.json")


def _load_tasks(path: Path) -> tuple[SearchTask, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return tuple(SearchTask.from_dict(item) for item in payload["tasks"])


def _audit_requirement(
    snapshot: EvidenceSnapshot,
    *,
    task_id: str,
    requirement: EvidenceRequirement,
    profile_id: str | None,
) -> dict[str, Any]:
    """Summarize annotation support for one contract requirement."""

    annotation_map = snapshot.annotation_map()
    source_ids = snapshot.source_ids_for_task(task_id)
    statuses = {
        source_id: annotation_map.get(
            (task_id, requirement.requirement_id, source_id),
            SupportStatus.MISSING,
        )
        for source_id in source_ids
    }
    return {
        "task_id": task_id,
        "profile_id": profile_id,
        "requirement_id": requirement.requirement_id,
        "kind": requirement.kind,
        "hard": requirement.hard,
        "supported_source_ids": [
            source_id for source_id, status in statuses.items() if status is SupportStatus.SUPPORTED
        ],
        "partial_source_ids": [source_id for source_id, status in statuses.items() if status is SupportStatus.PARTIAL],
        "contradicted_source_ids": [
            source_id for source_id, status in statuses.items() if status is SupportStatus.CONTRADICTED
        ],
        "missing_source_count": sum(status is SupportStatus.MISSING for status in statuses.values()),
        "has_supported_source": any(status is SupportStatus.SUPPORTED for status in statuses.values()),
    }


def audit_snapshot(
    tasks: tuple[SearchTask, ...],
    snapshot: EvidenceSnapshot,
    *,
    all_profiles: bool = False,
) -> dict[str, Any]:
    """Audit hard core and learner support coverage for the selected profile scope."""

    planner = KnowledgeStateGapPlanner()
    entries: list[dict[str, Any]] = []
    for task in tasks:
        core_requirements = tuple(item for item in task.evidence_requirements if item.kind == "core")
        entries.extend(
            _audit_requirement(
                snapshot,
                task_id=task.task_id,
                requirement=requirement,
                profile_id=None,
            )
            for requirement in core_requirements
        )
        profiles = task.profiles if all_profiles else (controlled_profiles(task)[1],)
        learner_entries: dict[str, str] = {}
        for profile in profiles:
            learner_gap = planner.plan(task, profile)
            for requirement in learner_gap.learner_requirements:
                learner_entries.setdefault(requirement.requirement_id, profile.student_id)
        entries.extend(
            _audit_requirement(
                snapshot,
                task_id=task.task_id,
                requirement=next(item for item in task.evidence_requirements if item.requirement_id == requirement_id),
                profile_id=profile_id,
            )
            for requirement_id, profile_id in sorted(learner_entries.items())
        )

    uncovered = [entry for entry in entries if not entry["has_supported_source"]]
    summary = {
        "task_count": len(tasks),
        "audited_requirement_count": len(entries),
        "supported_requirement_count": sum(entry["has_supported_source"] for entry in entries),
        "uncovered_requirement_count": len(uncovered),
        "partial_only_requirement_count": sum(
            bool(entry["partial_source_ids"]) and not entry["has_supported_source"] for entry in entries
        ),
        "hard_failure": bool(uncovered),
    }
    return {
        "schema_version": 1,
        "audit": "knowledge_state_search_snapshot_coverage",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_id": snapshot.manifest.snapshot_id,
        "scope": "hard_core_plus_all_task_profiles" if all_profiles else "hard_core_plus_controlled_single_gap",
        "summary": summary,
        "requirements": entries,
    }


def build_parser() -> argparse.ArgumentParser:
    """Build the snapshot audit command-line interface."""

    parser = argparse.ArgumentParser(description="Audit fixed snapshot evidence coverage.")
    parser.add_argument("--tasks", default=str(DEFAULT_TASKS))
    parser.add_argument("--snapshot", default=str(DEFAULT_SNAPSHOT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--all-profiles",
        action="store_true",
        help="Audit the learner obligations induced by every profile in the task file.",
    )
    return parser


def main() -> int:
    """Run and save the fixed-snapshot coverage audit."""

    args = build_parser().parse_args()
    tasks = _load_tasks(Path(args.tasks))
    snapshot = EvidenceSnapshot.load(args.snapshot)
    report = audit_snapshot(tasks, snapshot, all_profiles=args.all_profiles)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"Saved snapshot audit to {output}")
    return 1 if report["summary"]["hard_failure"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
