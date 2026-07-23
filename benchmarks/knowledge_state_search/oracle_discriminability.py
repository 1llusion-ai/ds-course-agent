"""Audit whether learner-specific queries can add evidence in the fixed snapshot."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from benchmarks.knowledge_state_search.evidence import EvidenceSnapshot, SupportStatus
from benchmarks.knowledge_state_search.gap_planner import KnowledgeStateGapPlanner
from benchmarks.knowledge_state_search.ledger import ClaimLevelEvaluator
from benchmarks.knowledge_state_search.models import EvidenceRequirement, SearchTask
from benchmarks.knowledge_state_search.snapshot_retriever import SnapshotRetriever

DEFAULT_TASKS = Path("benchmarks/data/knowledge_state_search_probe_v2.json")
DEFAULT_SNAPSHOT = Path("benchmarks/data/knowledge_state_search_snapshot_v2")
DEFAULT_QUERIES = Path("benchmarks/data/knowledge_state_search_oracle_queries_v2.json")
DEFAULT_OUTPUT = Path("var/artifacts/knowledge_state_search/oracle_discriminability_v2.json")


def load_tasks(path: Path) -> tuple[SearchTask, ...]:
    """Load typed search tasks."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    return tuple(SearchTask.from_dict(item) for item in payload["tasks"])


def load_queries(path: Path) -> dict[tuple[str, str], str]:
    """Load and flatten the hand-authored requirement query table."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        (task_id, requirement_id): query
        for task_id, task_queries in payload["queries"].items()
        for requirement_id, query in task_queries.items()
    }


def audit_discriminability(
    *,
    tasks: tuple[SearchTask, ...],
    snapshot: EvidenceSnapshot,
    queries: dict[tuple[str, str], str],
    top_k_values: tuple[int, ...],
) -> dict[str, Any]:
    """Compare core-only and gold-gap oracle retrieval for every profile."""

    _validate_query_coverage(tasks, queries)
    retriever = SnapshotRetriever(snapshot)
    evaluator = ClaimLevelEvaluator(snapshot)
    planner = KnowledgeStateGapPlanner()
    annotation_map = snapshot.annotation_map()
    results = []
    for top_k in top_k_values:
        for task in tasks:
            for profile in task.profiles:
                gap = planner.plan(task, profile)
                core_sources = _retrieve_requirements(
                    retriever,
                    queries,
                    task_id=task.task_id,
                    requirements=gap.core_requirements,
                    top_k=top_k,
                )
                gold_sources = tuple(
                    dict.fromkeys(
                        (
                            *core_sources,
                            *_retrieve_requirements(
                                retriever,
                                queries,
                                task_id=task.task_id,
                                requirements=gap.learner_requirements,
                                top_k=top_k,
                            ),
                        )
                    )
                )
                core_metrics = evaluator.evaluate(
                    task_id=task.task_id,
                    requirements=gap.all_requirements,
                    selected_source_ids=core_sources,
                )
                gold_metrics = evaluator.evaluate(
                    task_id=task.task_id,
                    requirements=gap.all_requirements,
                    selected_source_ids=gold_sources,
                )
                added_sources = tuple(source_id for source_id in gold_sources if source_id not in core_sources)
                results.append(
                    {
                        "top_k": top_k,
                        "task_id": task.task_id,
                        "student_id": profile.student_id,
                        "learner_requirement_ids": [item.requirement_id for item in gap.learner_requirements],
                        "core_only": _metrics_payload(core_metrics, core_sources),
                        "gold_gap": _metrics_payload(gold_metrics, gold_sources),
                        "learner_recall_delta": _delta(
                            gold_metrics.learner_recall,
                            core_metrics.learner_recall,
                        ),
                        "added_source_ids": list(added_sources),
                        "added_learner_support_source_ids": list(
                            _learner_support_sources(
                                task_id=task.task_id,
                                requirements=gap.learner_requirements,
                                source_ids=added_sources,
                                annotations=annotation_map,
                            )
                        ),
                    }
                )
    return {
        "schema_version": 1,
        "audit": "knowledge_state_search_oracle_discriminability",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_id": snapshot.manifest.snapshot_id,
        "top_k_values": list(top_k_values),
        "summary": {
            str(top_k): _summarize([item for item in results if item["top_k"] == top_k]) for top_k in top_k_values
        },
        "results": results,
    }


def _validate_query_coverage(
    tasks: tuple[SearchTask, ...],
    queries: dict[tuple[str, str], str],
) -> None:
    required = {
        (task.task_id, requirement.requirement_id) for task in tasks for requirement in task.evidence_requirements
    }
    missing = sorted(required - set(queries))
    if missing:
        raise ValueError(f"oracle query table is missing requirements: {missing}")


def _retrieve_requirements(
    retriever: SnapshotRetriever,
    queries: dict[tuple[str, str], str],
    *,
    task_id: str,
    requirements: tuple[EvidenceRequirement, ...],
    top_k: int,
) -> tuple[str, ...]:
    selected = []
    for requirement in requirements:
        query = queries[(task_id, requirement.requirement_id)]
        for hit in retriever.search(task_id=task_id, query=query, top_k=top_k):
            if hit.source_id not in selected:
                selected.append(hit.source_id)
    return tuple(selected)


def _metrics_payload(metrics: Any, source_ids: tuple[str, ...]) -> dict[str, Any]:
    return {
        "source_ids": list(source_ids),
        "source_count": len(source_ids),
        "hard_core_recall": metrics.hard_core_recall,
        "learner_recall": metrics.learner_recall,
        "evidence_precision": metrics.evidence_precision,
        "contradicted_rate": metrics.contradicted_rate,
        "unannotated_rate": metrics.unannotated_rate,
        "claim_conflict_rate": metrics.claim_conflict_rate,
    }


def _learner_support_sources(
    *,
    task_id: str,
    requirements: tuple[EvidenceRequirement, ...],
    source_ids: tuple[str, ...],
    annotations: dict[tuple[str, str, str], SupportStatus],
) -> tuple[str, ...]:
    return tuple(
        source_id
        for source_id in source_ids
        if any(
            annotations.get((task_id, requirement.requirement_id, source_id))
            in {SupportStatus.SUPPORTED, SupportStatus.PARTIAL}
            for requirement in requirements
        )
    )


def _summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    learner_cases = [item for item in results if item["learner_requirement_ids"]]
    deltas = [item["learner_recall_delta"] for item in learner_cases]
    return {
        "cases": len(results),
        "learner_gap_cases": len(learner_cases),
        "core_only_learner_recall": _mean(item["core_only"]["learner_recall"] for item in learner_cases),
        "gold_gap_learner_recall": _mean(item["gold_gap"]["learner_recall"] for item in learner_cases),
        "learner_recall_delta": _mean(deltas),
        "positive_learner_recall_delta_count": sum(value is not None and value > 0 for value in deltas),
        "zero_learner_recall_delta_count": sum(value == 0 for value in deltas),
        "added_source_count": _mean(len(item["added_source_ids"]) for item in learner_cases),
        "added_learner_support_source_count": _mean(
            len(item["added_learner_support_source_ids"]) for item in learner_cases
        ),
        "cases_without_added_learner_support": sum(
            not item["added_learner_support_source_ids"] for item in learner_cases
        ),
    }


def _delta(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return left - right


def _mean(values: Any) -> float | None:
    materialized = [value for value in values if value is not None]
    return mean(materialized) if materialized else None


def build_parser() -> argparse.ArgumentParser:
    """Build the oracle discriminability CLI."""

    parser = argparse.ArgumentParser(description="Audit learner-evidence discriminability.")
    parser.add_argument("--tasks", default=str(DEFAULT_TASKS))
    parser.add_argument("--snapshot", default=str(DEFAULT_SNAPSHOT))
    parser.add_argument("--queries", default=str(DEFAULT_QUERIES))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--top-k", type=int, action="append")
    return parser


def main() -> int:
    """Run and save the deterministic oracle audit."""

    args = build_parser().parse_args()
    report = audit_discriminability(
        tasks=load_tasks(Path(args.tasks)),
        snapshot=EvidenceSnapshot.load(args.snapshot),
        queries=load_queries(Path(args.queries)),
        top_k_values=tuple(args.top_k or (1, 3)),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"Saved oracle discriminability audit to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
