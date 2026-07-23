"""Run the first v3 method smoke without exposing gold learner claims."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from benchmarks.knowledge_state_search.confirmatory_evaluator_v3 import (
    AnnotationMap,
    build_annotation_map,
    conflict_rate,
    edge_recall,
    evaluate_claims,
    graph_completion_rate,
    mean_claim_metric,
    partial_only_rate,
    path_recall,
    path_recall_at,
    source_selection_metrics,
)
from benchmarks.knowledge_state_search.confirmatory_matrix_support import (
    adapt_profile,
    adapt_task,
    aggregate_method_telemetry,
    build_residual_plan,
    configured_model,
    execute_queries,
    failed_case,
    requirement_from_claim,
    summarize_results,
)
from benchmarks.knowledge_state_search.confirmatory_oracle_v3 import V3LexicalRetriever
from benchmarks.knowledge_state_search.confirmatory_pilot import load_confirmatory_pilot
from benchmarks.knowledge_state_search.confirmatory_schema import ConfirmatorySchema
from benchmarks.knowledge_state_search.models import (
    EvidenceGap,
    SearchTask,
    StudentProfile,
)
from benchmarks.knowledge_state_search.predicted_gap import predict_obligations, predicted_gap
from benchmarks.knowledge_state_search.prompt_probe import _request
from benchmarks.knowledge_state_search.selective_gap import (
    obligations_to_gap,
    parse_obligations,
    select_counterfactual_obligations,
)

DEFAULT_DATASET = Path("benchmarks/data/knowledge_state_search_confirmatory_v3_pilot")
DEFAULT_OUTPUT = Path("var/artifacts/knowledge_state_search/confirmatory_v3_matrix_smoke.json")
DEFAULT_BASE_URL = "http://model.mify.ai.srv/v1"
DEFAULT_MODEL = "xiaomi/mimo-v2.5-pro"
METHODS = ("M1N", "M1", "M2", "M2U", "M3", "M3U", "M3R")


def run_v3_matrix(
    *,
    api_key: str,
    base_url: str,
    model: str,
    schema: ConfirmatorySchema,
    methods: tuple[str, ...] = METHODS,
    repeats: int = 1,
    top_k: int = 3,
    max_queries: int = 3,
    source_budget: int = 6,
    timeout: float = 120.0,
    max_retries: int = 2,
    limit_tasks: int | None = None,
) -> dict[str, Any]:
    """Run a bounded v3 matrix with one planner action list per case."""

    schema.validate_pilot_contract()
    unknown_methods = set(methods) - set(METHODS)
    if unknown_methods:
        raise ValueError(f"unknown v3 methods: {sorted(unknown_methods)}")
    if repeats < 1 or top_k < 1 or max_queries < 1 or source_budget < 1:
        raise ValueError("repeats, top_k, max_queries, and source_budget must be positive")
    tasks = schema.tasks[:limit_tasks] if limit_tasks is not None else schema.tasks
    retriever = V3LexicalRetriever(schema)
    annotations = build_annotation_map(schema)
    results: list[dict[str, Any]] = []
    executed_model_calls = 0
    for repeat in range(1, repeats + 1):
        for task in tasks:
            claims = schema.claims_for_task(task.task_id)
            core_claims = tuple(claim for claim in claims if claim.hard)
            adapter_task = adapt_task(task.task_id, task.question, task.target_concepts, claims)
            core_gap = EvidenceGap(core_requirements=tuple(requirement_from_claim(claim) for claim in core_claims))
            task_profiles = schema.profiles_for_task(task.task_id)
            shared_plan_allocation = 1 / len(task_profiles)
            no_gap_profile = next(profile for profile in task_profiles if not schema.active_learner_claims(profile))
            neutral_profile = adapt_profile(no_gap_profile)
            shared_m1n_plan = None
            if "M1N" in methods or "M3R" in methods:
                executed_model_calls += 1
                shared_m1n_plan = _request(
                    api_key=api_key,
                    base_url=base_url,
                    model=model,
                    task=adapter_task,
                    profile=StudentProfile(
                        student_id=f"{task.task_id}_null_structured",
                        level="intermediate",
                    ),
                    variant="gap_planner",
                    gap=core_gap,
                    visible_requirement_ids=tuple(item.requirement_id for item in core_gap.all_requirements),
                    timeout=timeout,
                    max_retries=max_retries,
                    query_language="英文",
                )
            for profile in task_profiles:
                adapter_profile = adapt_profile(profile)
                gold_learner_claims = schema.active_learner_claims(profile)
                evaluation_claim_ids = tuple(claim.claim_id for claim in (*core_claims, *gold_learner_claims))
                if "M1N" in methods:
                    results.append(
                        _run_planner_case(
                            api_key=api_key,
                            base_url=base_url,
                            model=model,
                            method="M1N",
                            task=adapter_task,
                            profile=adapter_profile,
                            visible_gap=core_gap,
                            evaluation_claim_ids=evaluation_claim_ids,
                            schema=schema,
                            task_id=task.task_id,
                            retriever=retriever,
                            annotations=annotations,
                            repeat=repeat,
                            top_k=top_k,
                            max_queries=max_queries,
                            source_budget=source_budget,
                            timeout=timeout,
                            max_retries=max_retries,
                            variant="gap_planner",
                            planner_result_override=shared_m1n_plan,
                            planner_calls=0,
                            shared_planner_call_allocation=shared_plan_allocation,
                            planner_telemetry_weight=shared_plan_allocation,
                            extra={"shared_plan": True},
                        )
                    )
                if "M1" in methods:
                    executed_model_calls += 1
                    results.append(
                        _run_planner_case(
                            api_key=api_key,
                            base_url=base_url,
                            model=model,
                            method="M1",
                            task=adapter_task,
                            profile=adapter_profile,
                            visible_gap=core_gap,
                            evaluation_claim_ids=evaluation_claim_ids,
                            schema=schema,
                            task_id=task.task_id,
                            retriever=retriever,
                            annotations=annotations,
                            repeat=repeat,
                            top_k=top_k,
                            max_queries=max_queries,
                            source_budget=source_budget,
                            timeout=timeout,
                            max_retries=max_retries,
                            variant="profile_prompt",
                        )
                    )
                prediction_result: dict[str, Any] | None = None
                original_obligations = ()
                if {"M2", "M2U", "M3", "M3U", "M3R"} & set(methods):
                    executed_model_calls += 1
                    prediction_result = predict_obligations(
                        api_key=api_key,
                        base_url=base_url,
                        model=model,
                        task=adapter_task,
                        profile=adapter_profile,
                        timeout=timeout,
                        max_retries=max_retries,
                        neutral_learning_goal=no_gap_profile.learning_goal,
                    )
                    if prediction_result["error"] is None and prediction_result["prediction"]:
                        original_obligations = parse_obligations(prediction_result["prediction"])
                prediction_ok = bool(
                    prediction_result and prediction_result["error"] is None and prediction_result["prediction"]
                )
                if "M2" in methods or "M2U" in methods:
                    if not prediction_ok:
                        for method in ("M2", "M2U"):
                            if method in methods:
                                results.append(
                                    failed_case(
                                        method=method,
                                        task_id=task.task_id,
                                        profile_id=adapter_profile.student_id,
                                        repeat=repeat,
                                        error=f"predictor_failed: {prediction_result['error']}",
                                        prediction=prediction_result,
                                    )
                                )
                    else:
                        predicted = predicted_gap(
                            adapter_task,
                            prediction_result["prediction"],
                        )
                        for method, enforce_target_contract in (("M2", True), ("M2U", False)):
                            if method not in methods:
                                continue
                            executed_model_calls += 1
                            results.append(
                                _run_planner_case(
                                    api_key=api_key,
                                    base_url=base_url,
                                    model=model,
                                    method=method,
                                    task=adapter_task,
                                    profile=adapter_profile,
                                    visible_gap=predicted,
                                    evaluation_claim_ids=evaluation_claim_ids,
                                    schema=schema,
                                    task_id=task.task_id,
                                    retriever=retriever,
                                    annotations=annotations,
                                    repeat=repeat,
                                    top_k=top_k,
                                    max_queries=max_queries,
                                    source_budget=source_budget,
                                    timeout=timeout,
                                    max_retries=max_retries,
                                    variant="gap_planner",
                                    predictor_calls=1,
                                    enforce_target_contract=enforce_target_contract,
                                    extra={
                                        "prediction": prediction_result,
                                        "visible_gap": predicted.to_dict(),
                                    },
                                )
                            )
                if {"M3", "M3U", "M3R"} & set(methods):
                    if not prediction_ok:
                        for method in ("M3", "M3U", "M3R"):
                            if method in methods:
                                results.append(
                                    failed_case(
                                        method=method,
                                        task_id=task.task_id,
                                        profile_id=adapter_profile.student_id,
                                        repeat=repeat,
                                        error=f"predictor_failed: {prediction_result['error']}",
                                        prediction=prediction_result,
                                        shared_planner_call_allocation=(
                                            shared_plan_allocation if method == "M3R" else 0
                                        ),
                                        shared_plan_telemetry=(
                                            shared_m1n_plan.get("telemetry")
                                            if method == "M3R" and shared_m1n_plan
                                            else None
                                        ),
                                    )
                                )
                        continue
                    selected_obligations, selective_trace, selective_error = _selective_v3(
                        api_key=api_key,
                        base_url=base_url,
                        model=model,
                        task=adapter_task,
                        original_result=prediction_result,
                        original=original_obligations,
                        neutral_profile=neutral_profile,
                        neutral_learning_goal=no_gap_profile.learning_goal,
                        timeout=timeout,
                        max_retries=max_retries,
                    )
                    executed_model_calls += len(original_obligations)
                    if selective_error:
                        for method in ("M3", "M3U", "M3R"):
                            if method in methods:
                                results.append(
                                    failed_case(
                                        method=method,
                                        task_id=task.task_id,
                                        profile_id=adapter_profile.student_id,
                                        repeat=repeat,
                                        error=selective_error,
                                        prediction=prediction_result,
                                        selective_trace=selective_trace,
                                        shared_planner_call_allocation=(
                                            shared_plan_allocation if method == "M3R" else 0
                                        ),
                                        shared_plan_telemetry=(
                                            shared_m1n_plan.get("telemetry")
                                            if method == "M3R" and shared_m1n_plan
                                            else None
                                        ),
                                    )
                                )
                        continue
                    selective = obligations_to_gap(
                        adapter_task,
                        selected_obligations,
                        id_prefix="selective",
                    )
                    for method, enforce_target_contract in (("M3", True), ("M3U", False)):
                        if method not in methods:
                            continue
                        executed_model_calls += 1
                        results.append(
                            _run_planner_case(
                                api_key=api_key,
                                base_url=base_url,
                                model=model,
                                method=method,
                                task=adapter_task,
                                profile=adapter_profile,
                                visible_gap=selective,
                                evaluation_claim_ids=evaluation_claim_ids,
                                schema=schema,
                                task_id=task.task_id,
                                retriever=retriever,
                                annotations=annotations,
                                repeat=repeat,
                                top_k=top_k,
                                max_queries=max_queries,
                                source_budget=source_budget,
                                timeout=timeout,
                                max_retries=max_retries,
                                variant="gap_planner",
                                predictor_calls=1,
                                counterfactual_calls=len(original_obligations),
                                enforce_target_contract=enforce_target_contract,
                                extra={
                                    "prediction": prediction_result,
                                    "visible_gap": selective.to_dict(),
                                    "selective_trace": selective_trace,
                                },
                            )
                        )
                    if "M3R" in methods:
                        residual_gap = obligations_to_gap(
                            adapter_task,
                            selected_obligations,
                            id_prefix="residual",
                        )
                        residual_plan = build_residual_plan(
                            shared_m1n_plan.get("response") if shared_m1n_plan else None,
                            residual_gap,
                        )
                        results.append(
                            _run_planner_case(
                                api_key=api_key,
                                base_url=base_url,
                                model=model,
                                method="M3R",
                                task=adapter_task,
                                profile=adapter_profile,
                                visible_gap=residual_gap,
                                evaluation_claim_ids=evaluation_claim_ids,
                                schema=schema,
                                task_id=task.task_id,
                                retriever=retriever,
                                annotations=annotations,
                                repeat=repeat,
                                top_k=top_k,
                                max_queries=max_queries,
                                source_budget=source_budget,
                                timeout=timeout,
                                max_retries=max_retries,
                                variant="gap_planner",
                                planner_result_override={
                                    "response": residual_plan,
                                    "error": None,
                                },
                                planner_calls=0,
                                shared_planner_call_allocation=shared_plan_allocation,
                                planner_telemetry_weight=shared_plan_allocation,
                                predictor_calls=1,
                                counterfactual_calls=len(original_obligations),
                                extra={
                                    "prediction": prediction_result,
                                    "visible_gap": residual_gap.to_dict(),
                                    "selective_trace": selective_trace,
                                    "shared_core_plan": True,
                                    "shared_plan_telemetry": (
                                        shared_m1n_plan.get("telemetry") if shared_m1n_plan else None
                                    ),
                                },
                            )
                        )
    return {
        "schema_version": 3,
        "experiment": "knowledge_state_search_confirmatory_v3_matrix",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "benchmark_id": schema.manifest.benchmark_id,
        "executed_model_calls": executed_model_calls,
        "config": {
            "methods": list(methods),
            "repeats": repeats,
            "top_k": top_k,
            "max_queries": max_queries,
            "source_budget": source_budget,
            "base_url": base_url.rstrip("/"),
            "model": model,
        },
        "summary": summarize_results(results),
        "results": results,
    }


def _run_planner_case(
    *,
    api_key: str,
    base_url: str,
    model: str,
    method: str,
    task: SearchTask,
    profile: StudentProfile,
    visible_gap: EvidenceGap,
    evaluation_claim_ids: tuple[str, ...],
    schema: ConfirmatorySchema,
    task_id: str,
    retriever: V3LexicalRetriever,
    annotations: AnnotationMap,
    repeat: int,
    top_k: int,
    max_queries: int,
    source_budget: int,
    timeout: float,
    max_retries: int,
    variant: str,
    planner_result_override: dict[str, Any] | None = None,
    planner_calls: int = 1,
    shared_planner_call_allocation: float = 0,
    planner_telemetry_weight: float = 1,
    predictor_calls: int = 0,
    counterfactual_calls: int = 0,
    enforce_target_contract: bool = True,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    planner_result = planner_result_override or _request(
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
        required_target_ids=(
            tuple(item.requirement_id for item in visible_gap.learner_requirements) if enforce_target_contract else ()
        ),
        required_query_terms=(
            {item.requirement_id: item.search_terms for item in visible_gap.learner_requirements}
            if enforce_target_contract
            else {}
        ),
        enforce_target_contract=enforce_target_contract,
    )
    selected_source_ids, retrievals = execute_queries(
        retriever,
        task_id=task_id,
        plan=planner_result.get("response"),
        top_k=top_k,
        max_queries=max_queries,
        source_budget=source_budget,
    )
    metrics = evaluate_claims(
        task_id=task_id,
        claim_ids=evaluation_claim_ids,
        selected_source_ids=selected_source_ids,
        annotations=annotations,
    )
    core_claims = tuple(claim for claim in schema.claims_for_task(task_id) if claim.hard)
    learner_claims = tuple(
        claim for claim in schema.claims_for_task(task_id) if not claim.hard and claim.claim_id in evaluation_claim_ids
    )
    telemetry = aggregate_method_telemetry(
        planner_telemetry=planner_result.get("telemetry"),
        planner_weight=planner_telemetry_weight,
        prediction=(extra or {}).get("prediction"),
        selective_trace=(extra or {}).get("selective_trace"),
        shared_plan_telemetry=(extra or {}).get("shared_plan_telemetry"),
    )
    logical_model_calls = planner_calls + shared_planner_call_allocation + predictor_calls + counterfactual_calls
    result = {
        "task_id": task_id,
        "profile_id": profile.student_id,
        "repeat": repeat,
        "method": method,
        "error": planner_result.get("error"),
        "visible_gap": visible_gap.to_dict(),
        "planner": planner_result,
        "selected_source_ids": list(selected_source_ids),
        "retrievals": retrievals,
        "search_calls": len(retrievals),
        "retrieval_source_count": len(selected_source_ids),
        "cost": {
            "planner_calls": planner_calls,
            "shared_planner_call_allocation": shared_planner_call_allocation,
            "predictor_calls": predictor_calls,
            "counterfactual_calls": counterfactual_calls,
            "logical_model_calls": logical_model_calls,
            **telemetry,
        },
        "metrics": {
            "core_recall": mean_claim_metric(metrics, core_claims, "supported"),
            "learner_recall": mean_claim_metric(metrics, learner_claims, "supported"),
            "edge_recall": edge_recall(
                schema,
                task_id=task_id,
                selected_source_ids=selected_source_ids,
                annotations=annotations,
            ),
            "path_recall": path_recall(
                schema,
                task_id=task_id,
                selected_source_ids=selected_source_ids,
                annotations=annotations,
            ),
            "complete_path_recall_at_2": path_recall_at(
                schema,
                task_id=task_id,
                selected_source_ids=selected_source_ids,
                annotations=annotations,
                max_length=2,
            ),
            "complete_path_recall_at_3": path_recall_at(
                schema,
                task_id=task_id,
                selected_source_ids=selected_source_ids,
                annotations=annotations,
                max_length=3,
            ),
            "graph_completion_rate": graph_completion_rate(
                schema,
                task_id=task_id,
                claim_ids=evaluation_claim_ids,
                selected_source_ids=selected_source_ids,
                annotations=annotations,
            ),
            "partial_only_claim_rate": partial_only_rate(metrics),
            "claim_conflict_rate": conflict_rate(
                schema,
                task_id=task_id,
                selected_source_ids=selected_source_ids,
                annotations=annotations,
            ),
            **source_selection_metrics(
                schema,
                task_id=task_id,
                evaluation_claim_ids=evaluation_claim_ids,
                selected_source_ids=selected_source_ids,
                annotations=annotations,
            ),
        },
    }
    if extra:
        result.update(extra)
    return result


def _selective_v3(
    *,
    api_key: str,
    base_url: str,
    model: str,
    task: SearchTask,
    original_result: dict[str, Any] | None,
    original: tuple[Any, ...],
    neutral_profile: StudentProfile,
    neutral_learning_goal: str,
    timeout: float,
    max_retries: int,
) -> tuple[tuple[Any, ...], dict[str, Any], str | None]:
    """Apply the existing counterfactual gate to one adapted v3 profile."""

    counterfactuals: dict[Any, tuple[Any, ...]] = {}
    traces = []
    errors = []
    for obligation in original:
        result = predict_obligations(
            api_key=api_key,
            base_url=base_url,
            model=model,
            task=task,
            profile=neutral_profile,
            timeout=timeout,
            max_retries=max_retries,
            neutral_learning_goal=neutral_learning_goal,
        )
        parsed = parse_obligations(result["prediction"]) if result["error"] is None and result["prediction"] else ()
        if result["error"] is not None:
            errors.append(str(result["error"]))
        counterfactuals[obligation.trigger] = parsed
        traces.append(
            {
                "trigger": {
                    "field": obligation.trigger.field,
                    "value": obligation.trigger.value,
                },
                "neutral_profile": neutral_profile.to_dict(),
                "prediction": result,
            }
        )
    if errors:
        return (
            (),
            {
                "original_prediction": original_result,
                "counterfactual_predictions": traces,
                "selected_obligation_count": 0,
            },
            f"counterfactual_failed: {errors[0]}",
        )
    selected = select_counterfactual_obligations(original, counterfactuals)
    return (
        selected,
        {
            "original_prediction": original_result,
            "counterfactual_predictions": traces,
            "selected_obligation_count": len(selected),
        },
        None,
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the v3 matrix CLI."""

    parser = argparse.ArgumentParser(description="Run the v3 method smoke.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--api-key-env", default="PROFILE_EVAL_API_KEY")
    parser.add_argument("--base-url", default=os.environ.get("PROFILE_EVAL_BASE_URL") or DEFAULT_BASE_URL)
    parser.add_argument("--model", default=os.environ.get("PROFILE_EVAL_MODEL") or DEFAULT_MODEL)
    parser.add_argument("--methods", nargs="+", choices=METHODS, default=list(METHODS))
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--limit-tasks", type=int)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--max-queries", type=int, default=3)
    parser.add_argument("--source-budget", type=int, default=6)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--max-retries", type=int, default=2)
    return parser


def main() -> int:
    """Run and persist the v3 method smoke."""

    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
    args = build_parser().parse_args()
    api_key = os.environ.get(args.api_key_env) or os.environ.get("MIMO_API_KEY")
    if not api_key:
        print(f"API key not found. Set {args.api_key_env}.", file=sys.stderr)
        return 2
    schema = ConfirmatorySchema.load(args.dataset) if args.dataset.exists() else load_confirmatory_pilot()
    report = run_v3_matrix(
        api_key=api_key,
        base_url=args.base_url,
        model=configured_model(args.model),
        schema=schema,
        methods=tuple(args.methods),
        repeats=args.repeats,
        top_k=args.top_k,
        max_queries=args.max_queries,
        source_budget=args.source_budget,
        timeout=args.timeout,
        max_retries=args.max_retries,
        limit_tasks=args.limit_tasks,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"Saved v3 matrix report to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
