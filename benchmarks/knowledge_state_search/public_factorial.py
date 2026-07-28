"""Run the public-snapshot representation/executor attribution matrix."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from benchmarks.knowledge_state_search.controlled_profiles import (
    controlled_profiles,
)
from benchmarks.knowledge_state_search.evidence import EvidenceSnapshot
from benchmarks.knowledge_state_search.gap_planner import KnowledgeStateGapPlanner
from benchmarks.knowledge_state_search.ledger import ClaimLevelEvaluator
from benchmarks.knowledge_state_search.models import EvidenceGap, SearchTask, StudentProfile
from benchmarks.knowledge_state_search.offline_runner import (
    DEFAULT_BASE_URL,
    _all_task_profiles,
    _configured_model,
    _evaluate_case,
    _predict,
    _selective_prediction,
)
from benchmarks.knowledge_state_search.predicted_gap import predicted_gap
from benchmarks.knowledge_state_search.prompt_probe import _request
from benchmarks.knowledge_state_search.selective_gap import obligations_to_gap
from benchmarks.knowledge_state_search.snapshot_retriever import SnapshotRetriever

DEFAULT_TASKS = Path("benchmarks/data/knowledge_state_search_probe_v1.json")
DEFAULT_SNAPSHOT = Path("benchmarks/data/knowledge_state_search_snapshot_v1")
DEFAULT_OUTPUT = Path("var/artifacts/knowledge_state_search/public_factorial_v1.json")
METHODS = ("M1F", "M2F", "M2G", "M3F", "M3G")


def _load_env() -> None:
    """Load the repository experiment environment without overriding exports."""

    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)


def _load_tasks(path: Path) -> list[SearchTask]:
    """Load typed search tasks from a JSON task package."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    return [SearchTask.from_dict(item) for item in payload["tasks"]]


def _planner_request(
    *,
    api_key: str,
    base_url: str,
    model: str,
    task: SearchTask,
    profile: StudentProfile,
    visible_gap: EvidenceGap,
    representation: str,
    enforce_target_contract: bool,
    timeout: float,
    max_retries: int,
) -> dict[str, Any]:
    """Request one free or guarded planner execution for a representation."""

    variant = "profile_prompt" if representation == "M1" else "gap_planner"
    learner_requirements = visible_gap.learner_requirements if enforce_target_contract else ()
    return _request(
        api_key=api_key,
        base_url=base_url,
        model=model,
        task=task,
        profile=profile,
        variant=variant,
        gap=visible_gap,
        visible_requirement_ids=tuple(item.requirement_id for item in visible_gap.all_requirements),
        timeout=timeout,
        max_retries=max_retries,
        query_language="英文",
        required_target_ids=tuple(item.requirement_id for item in learner_requirements),
        required_query_terms={item.requirement_id: item.search_terms for item in learner_requirements},
        enforce_target_contract=enforce_target_contract,
    )


def _failed_result(
    *,
    task: SearchTask,
    profile: StudentProfile,
    method: str,
    evaluation_gap: EvidenceGap,
    error: str,
    repeat: int,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record a shared upstream failure without inventing retrieval metrics."""

    result: dict[str, Any] = {
        "task_id": task.task_id,
        "student_id": profile.student_id,
        "method": method,
        "error": error,
        "evaluation_gap": evaluation_gap.to_dict(),
        "visible_plan": None,
        "selected_source_ids": [],
        "retrievals": [],
        "search_calls": 0,
        "metrics": {
            "hard_core_recall": None,
            "learner_recall": None,
            "evidence_precision": None,
            "strict_supported_rate": None,
            "contradicted_rate": None,
            "unannotated_rate": None,
            "claim_conflict_rate": None,
            "assessments": [],
        },
        "repeat": repeat,
        "shared_plan": False,
    }
    if extra:
        result.update(extra)
    return result


def _append_planner_pair(
    *,
    results: list[dict[str, Any]],
    enabled_methods: set[str],
    evaluator: ClaimLevelEvaluator,
    retriever: SnapshotRetriever,
    task: SearchTask,
    profile: StudentProfile,
    evaluation_gap: EvidenceGap,
    visible_gap: EvidenceGap,
    method_free: str,
    method_guarded: str,
    free_plan: dict[str, Any] | None,
    guarded_plan: dict[str, Any] | None,
    top_k: int,
    max_queries: int,
    repeat: int,
    extra: dict[str, Any] | None = None,
) -> None:
    """Evaluate free and guarded executions from shared upstream state."""

    for method, plan, executor_mode in (
        (method_free, free_plan, "free"),
        (method_guarded, guarded_plan, "guarded"),
    ):
        if method not in enabled_methods:
            continue
        result = _evaluate_case(
            evaluator,
            retriever,
            task=task,
            profile=profile,
            method=method,
            evaluation_gap=evaluation_gap,
            plan_result=plan,
            top_k=top_k,
            max_queries=max_queries,
            extra={
                "repeat": repeat,
                "shared_plan": False,
                "representation_gap": visible_gap.to_dict(),
                "executor_mode": executor_mode,
                **(extra or {}),
            },
        )
        results.append(result)


def _summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize the matrix while preserving active-profile denominators."""

    grouped: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        grouped.setdefault(str(result["method"]), []).append(result)
    summary: dict[str, Any] = {}
    metric_names = (
        "hard_core_recall",
        "learner_recall",
        "evidence_precision",
        "strict_supported_rate",
        "contradicted_rate",
        "unannotated_rate",
        "claim_conflict_rate",
    )
    for method, items in sorted(grouped.items()):
        successful = [item for item in items if item.get("error") is None]
        active = [item for item in successful if item["evaluation_gap"]["learner_requirements"]]
        summary[method] = {
            "cases": len(items),
            "successful": len(successful),
            "failed": len(items) - len(successful),
            "active_profile_cases": len(active),
            "metrics": {
                name: {
                    "mean_all_successful": _mean(item["metrics"].get(name) for item in successful),
                    "mean_active_profiles": _mean(item["metrics"].get(name) for item in active),
                }
                for name in metric_names
            },
            "search_calls_mean": _mean(float(item["search_calls"]) for item in successful),
            "selected_sources_mean": _mean(float(len(item["selected_source_ids"])) for item in successful),
            "learner_target_rate": _learner_target_rate(successful),
        }
    return summary


def _mean(values: Any) -> float | None:
    """Average non-null values."""

    materialized = [float(value) for value in values if value is not None]
    return sum(materialized) / len(materialized) if materialized else None


def _learner_target_rate(results: list[dict[str, Any]]) -> float | None:
    """Measure whether executed actions target visible learner obligations."""

    active = [result for result in results if result["evaluation_gap"]["learner_requirements"]]
    if not active:
        return None
    targeted = 0
    for result in active:
        visible_gap = result.get("representation_gap") or {}
        learner_ids = {str(item["requirement_id"]) for item in visible_gap.get("learner_requirements", [])}
        actions = ((result.get("visible_plan") or {}).get("response") or {}).get("actions", [])
        action_targets = {
            str(target)
            for action in actions
            if isinstance(action, dict)
            for target in action.get("target_requirements", [])
        }
        if learner_ids & action_targets:
            targeted += 1
    return targeted / len(active)


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
    profile_provider: Any = controlled_profiles,
) -> dict[str, Any]:
    """Run the paired representation/executor attribution matrix."""

    unknown = set(methods) - set(METHODS)
    if unknown:
        raise ValueError(f"unknown public factorial methods: {sorted(unknown)}")
    retriever = SnapshotRetriever(snapshot)
    evaluator = ClaimLevelEvaluator(snapshot)
    gap_planner = KnowledgeStateGapPlanner()
    enabled_methods = set(methods)
    results: list[dict[str, Any]] = []

    for repeat in range(1, repeats + 1):
        for task in tasks:
            profiles = profile_provider(task)
            gold_gaps = {profile.student_id: gap_planner.plan(task, profile) for profile in profiles}
            for profile in profiles:
                evaluation_gap = gold_gaps[profile.student_id]
                core_gap = EvidenceGap(core_requirements=evaluation_gap.core_requirements)

                if "M1F" in methods:
                    plan = _planner_request(
                        api_key=api_key,
                        base_url=base_url,
                        model=model,
                        task=task,
                        profile=profile,
                        visible_gap=core_gap,
                        representation="M1",
                        enforce_target_contract=False,
                        timeout=timeout,
                        max_retries=max_retries,
                    )
                    results.append(
                        _evaluate_case(
                            evaluator,
                            retriever,
                            task=task,
                            profile=profile,
                            method="M1F",
                            evaluation_gap=evaluation_gap,
                            plan_result=plan,
                            top_k=top_k,
                            max_queries=max_queries,
                            extra={
                                "repeat": repeat,
                                "shared_plan": False,
                                "representation": "raw_profile",
                                "executor_mode": "free",
                                "representation_gap": core_gap.to_dict(),
                            },
                        )
                    )

                prediction_result: dict[str, Any] | None = None
                original_obligations: tuple[Any, ...] = ()
                if {"M2F", "M2G", "M3F", "M3G"} & set(methods):
                    prediction_result, original_obligations = _predict(
                        api_key=api_key,
                        base_url=base_url,
                        model=model,
                        task=task,
                        profile=profile,
                        timeout=timeout,
                        max_retries=max_retries,
                    )

                prediction_ok = bool(
                    prediction_result and prediction_result["error"] is None and prediction_result["prediction"]
                )
                if not prediction_ok and {"M2F", "M2G", "M3F", "M3G"} & set(methods):
                    error = (prediction_result or {}).get("error") or "predictor_failed"
                    for method in ("M2F", "M2G", "M3F", "M3G"):
                        if method in methods:
                            results.append(
                                _failed_result(
                                    task=task,
                                    profile=profile,
                                    method=method,
                                    evaluation_gap=evaluation_gap,
                                    error=f"predictor_failed: {error}",
                                    repeat=repeat,
                                    extra={
                                        "representation": (
                                            "predicted_gap" if method.startswith("M2") else "selective_gap"
                                        ),
                                        "executor_mode": ("guarded" if method.endswith("G") else "free"),
                                        "prediction": prediction_result,
                                    },
                                )
                            )
                    continue

                predicted = (
                    predicted_gap(task, prediction_result["prediction"]) if prediction_result is not None else core_gap
                )
                if {"M2F", "M2G"} & set(methods):
                    free_plan = (
                        _planner_request(
                            api_key=api_key,
                            base_url=base_url,
                            model=model,
                            task=task,
                            profile=profile,
                            visible_gap=predicted,
                            representation="M2",
                            enforce_target_contract=False,
                            timeout=timeout,
                            max_retries=max_retries,
                        )
                        if "M2F" in methods
                        else None
                    )
                    guarded_plan = (
                        _planner_request(
                            api_key=api_key,
                            base_url=base_url,
                            model=model,
                            task=task,
                            profile=profile,
                            visible_gap=predicted,
                            representation="M2",
                            enforce_target_contract=True,
                            timeout=timeout,
                            max_retries=max_retries,
                        )
                        if "M2G" in methods
                        else None
                    )
                    _append_planner_pair(
                        results=results,
                        enabled_methods=enabled_methods,
                        evaluator=evaluator,
                        retriever=retriever,
                        task=task,
                        profile=profile,
                        evaluation_gap=evaluation_gap,
                        visible_gap=predicted,
                        method_free="M2F",
                        method_guarded="M2G",
                        free_plan=free_plan,
                        guarded_plan=guarded_plan,
                        top_k=top_k,
                        max_queries=max_queries,
                        repeat=repeat,
                        extra={
                            "representation": "predicted_gap",
                            "prediction": prediction_result,
                            "visible_gap": predicted.to_dict(),
                        },
                    )

                if {"M3F", "M3G"} & set(methods):
                    selected, selective_trace = _selective_prediction(
                        api_key=api_key,
                        base_url=base_url,
                        model=model,
                        task=task,
                        profile=profile,
                        original_result=prediction_result or {"prediction": {"obligations": []}},
                        original=original_obligations,
                        timeout=timeout,
                        max_retries=max_retries,
                    )
                    selective = obligations_to_gap(
                        task,
                        selected,
                        id_prefix="selective",
                    )
                    free_plan = (
                        _planner_request(
                            api_key=api_key,
                            base_url=base_url,
                            model=model,
                            task=task,
                            profile=profile,
                            visible_gap=selective,
                            representation="M3",
                            enforce_target_contract=False,
                            timeout=timeout,
                            max_retries=max_retries,
                        )
                        if "M3F" in methods
                        else None
                    )
                    guarded_plan = (
                        _planner_request(
                            api_key=api_key,
                            base_url=base_url,
                            model=model,
                            task=task,
                            profile=profile,
                            visible_gap=selective,
                            representation="M3",
                            enforce_target_contract=True,
                            timeout=timeout,
                            max_retries=max_retries,
                        )
                        if "M3G" in methods
                        else None
                    )
                    _append_planner_pair(
                        results=results,
                        enabled_methods=enabled_methods,
                        evaluator=evaluator,
                        retriever=retriever,
                        task=task,
                        profile=profile,
                        evaluation_gap=evaluation_gap,
                        visible_gap=selective,
                        method_free="M3F",
                        method_guarded="M3G",
                        free_plan=free_plan,
                        guarded_plan=guarded_plan,
                        top_k=top_k,
                        max_queries=max_queries,
                        repeat=repeat,
                        extra={
                            "representation": "selective_gap",
                            "prediction": prediction_result,
                            "visible_gap": selective.to_dict(),
                            "selective_trace": selective_trace,
                        },
                    )

    return {
        "schema_version": 1,
        "experiment": "knowledge_state_search_public_representation_executor_factorial",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config": {
            "methods": list(methods),
            "repeats": repeats,
            "top_k": top_k,
            "max_queries": max_queries,
            "snapshot_id": snapshot.manifest.snapshot_id,
            "model": model,
            "m1_guarded_status": "not_defined_without_gold_or_structured_obligation_injection",
        },
        "summary": _summary(results),
        "results": results,
    }


def build_parser() -> argparse.ArgumentParser:
    """Build the public factorial command-line interface."""

    parser = argparse.ArgumentParser(description="Run the public representation/executor factorial.")
    parser.add_argument("--tasks", default=str(DEFAULT_TASKS))
    parser.add_argument("--snapshot", default=str(DEFAULT_SNAPSHOT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--api-key-env", default="PROFILE_EVAL_API_KEY")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("PROFILE_EVAL_BASE_URL") or os.environ.get("MIFY_BASE_URL") or DEFAULT_BASE_URL,
    )
    parser.add_argument("--model", default=_configured_model())
    parser.add_argument("--method", action="append", choices=METHODS)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--max-queries", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument(
        "--all-profiles",
        action="store_true",
        help="Run every profile declared in the task file.",
    )
    return parser


def main() -> int:
    """Run and save the public factorial matrix."""

    _load_env()
    args = build_parser().parse_args()
    api_key = os.environ.get(args.api_key_env) or os.environ.get("MIMO_API_KEY") or os.environ.get("JUDGE_API_KEY")
    if not api_key:
        print("API key not found.", file=sys.stderr)
        return 2
    tasks = _load_tasks(Path(args.tasks))
    methods = tuple(args.method or METHODS)
    payload = run_matrix(
        api_key=api_key,
        base_url=args.base_url,
        model=args.model,
        tasks=tasks,
        snapshot=EvidenceSnapshot.load(args.snapshot),
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
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    print(f"Saved public factorial result to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
