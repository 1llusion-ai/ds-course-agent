"""Run the fair M0-M5 planner matrix against a fixed evidence snapshot."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from benchmarks.knowledge_state_search.controlled_profiles import (
    controlled_profiles,
    wrong_gap,
)
from benchmarks.knowledge_state_search.evidence import EvidenceSnapshot
from benchmarks.knowledge_state_search.gap_planner import KnowledgeStateGapPlanner
from benchmarks.knowledge_state_search.ledger import ClaimLevelEvaluator
from benchmarks.knowledge_state_search.models import EvidenceGap, SearchTask, StudentProfile
from benchmarks.knowledge_state_search.predicted_gap import predict_obligations, predicted_gap
from benchmarks.knowledge_state_search.prompt_probe import _request
from benchmarks.knowledge_state_search.selective_gap import (
    neutralize_trigger,
    obligations_to_gap,
    parse_obligations,
    select_counterfactual_obligations,
)
from benchmarks.knowledge_state_search.snapshot_retriever import SnapshotRetriever

DEFAULT_TASKS = Path("benchmarks/data/knowledge_state_search_probe_v1.json")
DEFAULT_SNAPSHOT = Path("benchmarks/data/knowledge_state_search_snapshot_v1")
DEFAULT_OUTPUT = Path("var/artifacts/knowledge_state_search/offline_smoke_v1.json")
DEFAULT_BASE_URL = "http://model.mify.ai.srv/v1"
DEFAULT_MODEL = "xiaomi/mimo-v2.5-pro"
METHODS = ("M0", "M1", "M2", "M3", "M4", "M5")


def _load_tasks(path: Path) -> list[SearchTask]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [SearchTask.from_dict(item) for item in payload["tasks"]]


def _load_env() -> None:
    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)


def _all_task_profiles(task: SearchTask) -> tuple[StudentProfile, ...]:
    """Return every profile declared by a confirmatory task file."""

    return task.profiles


def _configured_model() -> str:
    """Resolve a provider-qualified model name from the local experiment env."""

    model = os.environ.get("PROFILE_EVAL_MODEL") or os.environ.get("MIMO_MODEL") or DEFAULT_MODEL
    provider = os.environ.get("MIMO_PROVIDER", "").strip()
    if provider and "/" not in model:
        return f"{provider}/{model}"
    return model


def _plan_requirements(gap: EvidenceGap) -> tuple[str, ...]:
    return tuple(item.requirement_id for item in gap.all_requirements)


def _execute_queries(
    retriever: SnapshotRetriever,
    *,
    task_id: str,
    plan: dict[str, Any] | None,
    top_k: int,
    max_queries: int,
) -> tuple[tuple[str, ...], list[dict[str, Any]]]:
    """Retrieve source IDs from planner queries without using annotations."""

    if not plan:
        return (), []
    actions = plan.get("actions", [])
    queries: list[str] = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        if str(action.get("type", "")).upper() not in {"SEARCH", "REFINE"}:
            continue
        query = str(action.get("query", "")).strip()
        if query and query not in queries:
            queries.append(query)
    selected: list[str] = []
    retrievals: list[dict[str, Any]] = []
    for query in queries[:max_queries]:
        hits = retriever.search(task_id=task_id, query=query, top_k=top_k)
        for hit in hits:
            if hit.source_id not in selected:
                selected.append(hit.source_id)
        retrievals.append(
            {
                "query": query,
                "hits": [{"source_id": hit.source_id, "title": hit.title, "score": hit.score} for hit in hits],
            }
        )
    return tuple(selected), retrievals


def _request_plan(
    *,
    api_key: str,
    base_url: str,
    model: str,
    task: SearchTask,
    profile: StudentProfile,
    variant: str,
    visible_gap: EvidenceGap,
    evaluation_gap: EvidenceGap,
    timeout: float,
    max_retries: int,
) -> dict[str, Any]:
    """Request one planner trace with a shared English-query contract."""

    return _request(
        api_key=api_key,
        base_url=base_url,
        model=model,
        task=task,
        profile=profile,
        variant=variant,
        gap=evaluation_gap if variant != "gap_planner" else visible_gap,
        visible_requirement_ids=_plan_requirements(visible_gap),
        timeout=timeout,
        max_retries=max_retries,
        query_language="英文",
    )


def _predict(
    *,
    api_key: str,
    base_url: str,
    model: str,
    task: SearchTask,
    profile: StudentProfile,
    timeout: float,
    max_retries: int,
) -> tuple[dict[str, Any], tuple[Any, ...]]:
    result = predict_obligations(
        api_key=api_key,
        base_url=base_url,
        model=model,
        task=task,
        profile=profile,
        timeout=timeout,
        max_retries=max_retries,
    )
    if result["error"] or not result["prediction"]:
        return result, ()
    return result, parse_obligations(result["prediction"])


def _selective_prediction(
    *,
    api_key: str,
    base_url: str,
    model: str,
    task: SearchTask,
    profile: StudentProfile,
    original_result: dict[str, Any],
    original: tuple[Any, ...],
    timeout: float,
    max_retries: int,
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """Neutralize each trigger and retain only causally necessary obligations."""

    counterfactuals: dict[Any, tuple[Any, ...]] = {}
    counterfactual_results: list[dict[str, Any]] = []
    for obligation in original:
        trigger = obligation.trigger
        neutralized = neutralize_trigger(profile, trigger)
        result, parsed = _predict(
            api_key=api_key,
            base_url=base_url,
            model=model,
            task=task,
            profile=neutralized,
            timeout=timeout,
            max_retries=max_retries,
        )
        counterfactuals[trigger] = parsed
        counterfactual_results.append(
            {
                "trigger": {"field": trigger.field, "value": trigger.value},
                "profile": neutralized.to_dict(),
                "prediction": result,
            }
        )
    selected = select_counterfactual_obligations(original, counterfactuals)
    return selected, {
        "original_prediction": original_result,
        "counterfactual_predictions": counterfactual_results,
        "selected_obligations": [
            {
                "kind": item.kind,
                "concept": item.concept,
                "claim": item.claim,
                "search_terms": list(item.search_terms),
                "trigger": {"field": item.trigger.field, "value": item.trigger.value},
                "priority": item.priority,
            }
            for item in selected
        ],
    }


def _evaluate_case(
    evaluator: ClaimLevelEvaluator,
    retriever: SnapshotRetriever,
    *,
    task: SearchTask,
    profile: StudentProfile,
    method: str,
    evaluation_gap: EvidenceGap,
    plan_result: dict[str, Any] | None,
    top_k: int,
    max_queries: int,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected_source_ids, retrievals = _execute_queries(
        retriever,
        task_id=task.task_id,
        plan=(plan_result or {}).get("response") if plan_result else None,
        top_k=top_k,
        max_queries=max_queries,
    )
    metrics = evaluator.evaluate(
        task_id=task.task_id,
        requirements=evaluation_gap.all_requirements,
        selected_source_ids=selected_source_ids,
    )
    result = {
        "task_id": task.task_id,
        "student_id": profile.student_id,
        "method": method,
        "error": (plan_result or {}).get("error") if plan_result else None,
        "evaluation_gap": evaluation_gap.to_dict(),
        "visible_plan": plan_result,
        "selected_source_ids": list(selected_source_ids),
        "retrievals": retrievals,
        "search_calls": len(retrievals),
        "metrics": {
            "hard_core_recall": metrics.hard_core_recall,
            "learner_recall": metrics.learner_recall,
            "evidence_precision": metrics.evidence_precision,
            "strict_supported_rate": metrics.strict_supported_rate,
            "contradicted_rate": metrics.contradicted_rate,
            "unannotated_rate": metrics.unannotated_rate,
            "claim_conflict_rate": metrics.claim_conflict_rate,
            "assessments": [
                {
                    "requirement_id": item.requirement_id,
                    "kind": item.kind,
                    "status": item.status.value,
                    "conflicted": item.conflicted,
                    "source_ids": list(item.source_ids),
                }
                for item in metrics.assessments
            ],
        },
    }
    if extra:
        result.update(extra)
    return result


def _mean(values: list[float | None]) -> float | None:
    usable = [value for value in values if value is not None]
    return sum(usable) / len(usable) if usable else None


def _summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        grouped[str(result["method"])].append(result)
    summary: dict[str, Any] = {}
    for method, items in sorted(grouped.items()):
        metrics = [item["metrics"] for item in items if item.get("error") is None]
        summary[method] = {
            "cases": len(items),
            "successful": len(metrics),
            "hard_core_recall_mean": _mean([item["hard_core_recall"] for item in metrics]),
            "learner_recall_mean": _mean([item["learner_recall"] for item in metrics]),
            "evidence_precision_mean": _mean([item["evidence_precision"] for item in metrics]),
            "strict_supported_rate_mean": _mean([item["strict_supported_rate"] for item in metrics]),
            "contradicted_rate_mean": _mean([item["contradicted_rate"] for item in metrics]),
            "unannotated_rate_mean": _mean([item["unannotated_rate"] for item in metrics]),
            "claim_conflict_rate_mean": _mean([item["claim_conflict_rate"] for item in metrics]),
            "search_calls_mean": _mean([float(item["search_calls"]) for item in items]),
        }
    return summary


def run_matrix(
    *,
    api_key: str,
    base_url: str,
    model: str,
    tasks: list[SearchTask],
    snapshot: EvidenceSnapshot,
    methods: tuple[str, ...],
    repeats: int,
    top_k: int,
    max_queries: int,
    timeout: float,
    max_retries: int,
    profile_provider: Callable[[SearchTask], tuple[StudentProfile, ...]] = controlled_profiles,
) -> dict[str, Any]:
    """Run the bounded M0-M5 matrix sequentially for auditability."""

    retriever = SnapshotRetriever(snapshot)
    evaluator = ClaimLevelEvaluator(snapshot)
    gap_planner = KnowledgeStateGapPlanner()
    results: list[dict[str, Any]] = []

    for repeat in range(1, repeats + 1):
        for task in tasks:
            profiles = profile_provider(task)
            if not profiles:
                raise ValueError(f"task has no profiles: {task.task_id}")
            no_gap = profiles[0]
            single_gap = profiles[1] if len(profiles) > 1 else None
            gold_gaps = {profile.student_id: gap_planner.plan(task, profile) for profile in profiles}
            shared_m0_plan: dict[str, Any] | None = None
            if "M0" in methods:
                shared_m0_plan = _request_plan(
                    api_key=api_key,
                    base_url=base_url,
                    model=model,
                    task=task,
                    profile=no_gap,
                    variant="generic",
                    visible_gap=EvidenceGap(core_requirements=gold_gaps[no_gap.student_id].core_requirements),
                    evaluation_gap=gold_gaps[no_gap.student_id],
                    timeout=timeout,
                    max_retries=max_retries,
                )
                for profile in profiles:
                    results.append(
                        _evaluate_case(
                            evaluator,
                            retriever,
                            task=task,
                            profile=profile,
                            method="M0",
                            evaluation_gap=gold_gaps[profile.student_id],
                            plan_result=shared_m0_plan,
                            top_k=top_k,
                            max_queries=max_queries,
                            extra={"repeat": repeat, "shared_plan": True},
                        )
                    )
            for profile in profiles:
                evaluation_gap = gold_gaps[profile.student_id]
                core_gap = EvidenceGap(core_requirements=evaluation_gap.core_requirements)
                if "M1" in methods:
                    plan = _request_plan(
                        api_key=api_key,
                        base_url=base_url,
                        model=model,
                        task=task,
                        profile=profile,
                        variant="profile_prompt",
                        visible_gap=core_gap,
                        evaluation_gap=evaluation_gap,
                        timeout=timeout,
                        max_retries=max_retries,
                    )
                    results.append(
                        _evaluate_case(
                            evaluator,
                            retriever,
                            task=task,
                            profile=profile,
                            method="M1",
                            evaluation_gap=evaluation_gap,
                            plan_result=plan,
                            top_k=top_k,
                            max_queries=max_queries,
                            extra={"repeat": repeat, "shared_plan": False},
                        )
                    )
                original_result: dict[str, Any] | None = None
                original_obligations: tuple[Any, ...] = ()
                predicted = EvidenceGap(core_requirements=evaluation_gap.core_requirements)
                if "M2" in methods or "M3" in methods:
                    original_result, original_obligations = _predict(
                        api_key=api_key,
                        base_url=base_url,
                        model=model,
                        task=task,
                        profile=profile,
                        timeout=timeout,
                        max_retries=max_retries,
                    )
                    predicted = predicted_gap(
                        task,
                        original_result["prediction"] or {"obligations": []},
                    )
                if "M2" in methods:
                    plan = _request_plan(
                        api_key=api_key,
                        base_url=base_url,
                        model=model,
                        task=task,
                        profile=profile,
                        variant="gap_planner",
                        visible_gap=predicted,
                        evaluation_gap=evaluation_gap,
                        timeout=timeout,
                        max_retries=max_retries,
                    )
                    results.append(
                        _evaluate_case(
                            evaluator,
                            retriever,
                            task=task,
                            profile=profile,
                            method="M2",
                            evaluation_gap=evaluation_gap,
                            plan_result=plan,
                            top_k=top_k,
                            max_queries=max_queries,
                            extra={
                                "repeat": repeat,
                                "shared_plan": False,
                                "prediction": original_result,
                                "visible_gap": predicted.to_dict(),
                            },
                        )
                    )
                if "M3" in methods:
                    selected, selective_trace = _selective_prediction(
                        api_key=api_key,
                        base_url=base_url,
                        model=model,
                        task=task,
                        profile=profile,
                        original_result=original_result or {"prediction": {"obligations": []}},
                        original=original_obligations,
                        timeout=timeout,
                        max_retries=max_retries,
                    )
                    selective = obligations_to_gap(task, selected, id_prefix="selective")
                    plan = _request_plan(
                        api_key=api_key,
                        base_url=base_url,
                        model=model,
                        task=task,
                        profile=profile,
                        variant="gap_planner",
                        visible_gap=selective,
                        evaluation_gap=evaluation_gap,
                        timeout=timeout,
                        max_retries=max_retries,
                    )
                    results.append(
                        _evaluate_case(
                            evaluator,
                            retriever,
                            task=task,
                            profile=profile,
                            method="M3",
                            evaluation_gap=evaluation_gap,
                            plan_result=plan,
                            top_k=top_k,
                            max_queries=max_queries,
                            extra={
                                "repeat": repeat,
                                "shared_plan": False,
                                "visible_gap": selective.to_dict(),
                                "selective_trace": selective_trace,
                            },
                        )
                    )
                if "M4" in methods:
                    plan = _request_plan(
                        api_key=api_key,
                        base_url=base_url,
                        model=model,
                        task=task,
                        profile=profile,
                        variant="gap_planner",
                        visible_gap=evaluation_gap,
                        evaluation_gap=evaluation_gap,
                        timeout=timeout,
                        max_retries=max_retries,
                    )
                    results.append(
                        _evaluate_case(
                            evaluator,
                            retriever,
                            task=task,
                            profile=profile,
                            method="M4",
                            evaluation_gap=evaluation_gap,
                            plan_result=plan,
                            top_k=top_k,
                            max_queries=max_queries,
                            extra={"repeat": repeat, "shared_plan": False},
                        )
                    )
                if "M5" in methods and single_gap is not None and profile.student_id == single_gap.student_id:
                    mismatched = wrong_gap(task)
                    plan = _request_plan(
                        api_key=api_key,
                        base_url=base_url,
                        model=model,
                        task=task,
                        profile=profile,
                        variant="gap_planner",
                        visible_gap=mismatched,
                        evaluation_gap=evaluation_gap,
                        timeout=timeout,
                        max_retries=max_retries,
                    )
                    results.append(
                        _evaluate_case(
                            evaluator,
                            retriever,
                            task=task,
                            profile=profile,
                            method="M5",
                            evaluation_gap=evaluation_gap,
                            plan_result=plan,
                            top_k=top_k,
                            max_queries=max_queries,
                            extra={"repeat": repeat, "shared_plan": False, "visible_gap": mismatched.to_dict()},
                        )
                    )
    return {
        "schema_version": 1,
        "experiment": "knowledge_state_search_fixed_snapshot_m0_m5",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config": {
            "methods": list(methods),
            "repeats": repeats,
            "top_k": top_k,
            "max_queries": max_queries,
            "snapshot_id": snapshot.manifest.snapshot_id,
            "model": model,
        },
        "summary": _summarize(results),
        "results": results,
    }


def build_parser() -> argparse.ArgumentParser:
    """Build the offline matrix CLI."""

    parser = argparse.ArgumentParser(description="Run M0-M5 over a fixed evidence snapshot.")
    parser.add_argument("--tasks", default=str(DEFAULT_TASKS))
    parser.add_argument("--snapshot", default=str(DEFAULT_SNAPSHOT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--api-key-env", default="PROFILE_EVAL_API_KEY")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("PROFILE_EVAL_BASE_URL") or os.environ.get("MIFY_BASE_URL") or DEFAULT_BASE_URL,
    )
    parser.add_argument(
        "--model",
        default=_configured_model(),
    )
    parser.add_argument("--method", action="append", choices=METHODS)
    parser.add_argument("--limit-tasks", type=int, default=0)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--top-k", type=int, default=1)
    parser.add_argument("--max-queries", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument(
        "--all-profiles",
        action="store_true",
        help="Run every profile declared in the task file instead of the v1 controlled pair.",
    )
    return parser


def main() -> int:
    """Run and save the fixed-snapshot matrix."""

    _load_env()
    args = build_parser().parse_args()
    api_key = os.environ.get(args.api_key_env) or os.environ.get("MIMO_API_KEY") or os.environ.get("JUDGE_API_KEY")
    if not api_key:
        print("API key not found.", file=sys.stderr)
        return 2
    tasks = _load_tasks(Path(args.tasks))
    if args.limit_tasks > 0:
        tasks = tasks[: args.limit_tasks]
    snapshot = EvidenceSnapshot.load(args.snapshot)
    methods = tuple(args.method or METHODS)
    payload = run_matrix(
        api_key=api_key,
        base_url=args.base_url,
        model=args.model,
        tasks=tasks,
        snapshot=snapshot,
        methods=methods,
        repeats=max(1, args.repeats),
        top_k=max(1, args.top_k),
        max_queries=max(1, args.max_queries),
        timeout=args.timeout,
        max_retries=max(1, args.max_retries),
        profile_provider=_all_task_profiles if args.all_profiles else controlled_profiles,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    print(f"Saved fixed-snapshot result to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
