"""Adapters and deterministic query execution for the v3 method matrix."""

from __future__ import annotations

import os
from typing import Any

from benchmarks.knowledge_state_search.confirmatory_oracle_v3 import (
    V3LexicalRetriever,
)
from benchmarks.knowledge_state_search.confirmatory_schema import (
    CanonicalClaim,
    LearnerProfile,
)
from benchmarks.knowledge_state_search.models import (
    EvidenceGap,
    EvidenceRequirement,
    SearchTask,
    StudentProfile,
)


def execute_queries(
    retriever: V3LexicalRetriever,
    *,
    task_id: str,
    plan: dict[str, Any] | None,
    top_k: int,
    max_queries: int,
    source_budget: int,
) -> tuple[tuple[str, ...], list[dict[str, Any]]]:
    """Execute planner queries against the frozen v3 source snapshot."""

    if not plan:
        return (), []
    queries = []
    for action in plan.get("actions", []):
        if not isinstance(action, dict):
            continue
        if str(action.get("type", "")).upper() not in {"SEARCH", "REFINE"}:
            continue
        query = str(action.get("query", "")).strip()
        if query and query not in queries:
            queries.append(query)
    selected = []
    retrievals = []
    for query in queries[:max_queries]:
        hits = retriever.search(task_id=task_id, query=query, top_k=top_k)
        for source_id, _score in hits:
            if source_id not in selected:
                selected.append(source_id)
            if len(selected) >= source_budget:
                break
        retrievals.append(
            {
                "query": query,
                "hits": [{"source_id": source_id, "score": score} for source_id, score in hits],
            }
        )
        if len(selected) >= source_budget:
            break
    return tuple(selected[:source_budget]), retrievals


def adapt_task(
    task_id: str,
    question: str,
    target_concepts: tuple[str, ...],
    claims: tuple[CanonicalClaim, ...],
) -> SearchTask:
    """Expose only the shared core contract through the legacy planner interface."""

    return SearchTask(
        task_id=task_id,
        question=question,
        target_concepts=target_concepts,
        evidence_requirements=tuple(requirement_from_claim(claim) for claim in claims if claim.hard),
        profiles=(),
    )


def adapt_profile(profile: LearnerProfile) -> StudentProfile:
    """Convert a v3 profile without adding gold claim identifiers."""

    return StudentProfile(
        student_id=profile.profile_id,
        level=profile.level,
        mastered_concepts=profile.mastered_concepts,
        weak_concepts=profile.weak_concepts,
        misconceptions=profile.misconceptions,
        learning_goal=profile.learning_goal,
    )


def build_residual_plan(
    core_plan: dict[str, Any] | None,
    learner_gap: EvidenceGap,
) -> dict[str, Any]:
    """Keep shared core anchors and append one deterministic learner query."""

    if not core_plan:
        return {"actions": []}
    actions = [
        action
        for action in core_plan.get("actions", [])
        if isinstance(action, dict) and str(action.get("type", "")).upper() in {"SEARCH", "REFINE"}
    ]
    if not learner_gap.learner_requirements:
        return {"actions": actions[:3], "stop_reason": "no learner obligation"}
    core_actions = actions[:2]
    query = " ".join(
        term for requirement in learner_gap.learner_requirements for term in requirement.search_terms
    ).strip()
    if not query:
        query = " ".join(requirement.concept for requirement in learner_gap.learner_requirements)
    residual = {
        "type": "SEARCH",
        "query": query,
        "purpose": "retrieve residual learner evidence",
        "target_requirements": [requirement.requirement_id for requirement in learner_gap.learner_requirements],
    }
    return {
        "actions": [*core_actions, residual],
        "stop_reason": "core anchors plus residual learner evidence",
    }


def requirement_from_claim(claim: CanonicalClaim) -> EvidenceRequirement:
    """Convert one shared core claim into the planner's typed requirement."""

    return EvidenceRequirement(
        requirement_id=claim.claim_id,
        kind="core",
        concept=claim.concept,
        description=claim.description,
        search_terms=(),
        hard=True,
        priority=claim.priority,
    )


def mean_optional(values: list[float | None]) -> float | None:
    """Average non-null metrics."""

    usable = [value for value in values if value is not None]
    return sum(usable) / len(usable) if usable else None


def aggregate_method_telemetry(
    *,
    planner_telemetry: dict[str, Any] | None = None,
    planner_weight: float = 1,
    prediction: dict[str, Any] | None = None,
    selective_trace: dict[str, Any] | None = None,
    shared_plan_telemetry: dict[str, Any] | None = None,
) -> dict[str, int | float | None]:
    """Aggregate request telemetry while allocating shared planner work explicitly."""

    sources: list[tuple[dict[str, Any], float]] = []
    if planner_telemetry:
        sources.append((planner_telemetry, planner_weight))
    if shared_plan_telemetry:
        sources.append((shared_plan_telemetry, planner_weight))
    if prediction and isinstance(prediction.get("telemetry"), dict):
        sources.append((prediction["telemetry"], 1))
    if selective_trace:
        for item in selective_trace.get("counterfactual_predictions", []):
            counterfactual = item.get("prediction") if isinstance(item, dict) else None
            if isinstance(counterfactual, dict) and isinstance(counterfactual.get("telemetry"), dict):
                sources.append((counterfactual["telemetry"], 1))

    result: dict[str, int | float | None] = {}
    for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
        values = [(telemetry.get(field), weight) for telemetry, weight in sources]
        if not values or any(value is None for value, _weight in values):
            result[field] = None
        else:
            result[field] = sum(float(value) * weight for value, weight in values)
    latency_values = [
        float(telemetry["latency_seconds"]) * weight
        for telemetry, weight in sources
        if telemetry.get("latency_seconds") is not None
    ]
    result["latency_seconds"] = sum(latency_values) if latency_values else None
    return result


def failed_case(
    *,
    method: str,
    task_id: str,
    profile_id: str,
    repeat: int,
    error: str,
    prediction: dict[str, Any] | None,
    selective_trace: dict[str, Any] | None = None,
    shared_planner_call_allocation: float = 0,
    shared_plan_telemetry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record an upstream failure without pretending that retrieval ran."""

    counterfactual_calls = len(selective_trace.get("counterfactual_predictions", [])) if selective_trace else 0
    telemetry = aggregate_method_telemetry(
        planner_weight=shared_planner_call_allocation,
        prediction=prediction,
        selective_trace=selective_trace,
        shared_plan_telemetry=shared_plan_telemetry,
    )
    return {
        "task_id": task_id,
        "profile_id": profile_id,
        "repeat": repeat,
        "method": method,
        "error": error,
        "prediction": prediction,
        "selective_trace": selective_trace,
        "visible_gap": None,
        "planner": None,
        "selected_source_ids": [],
        "retrievals": [],
        "search_calls": 0,
        "retrieval_source_count": 0,
        "cost": {
            "planner_calls": 0,
            "shared_planner_call_allocation": shared_planner_call_allocation,
            "predictor_calls": 1,
            "counterfactual_calls": counterfactual_calls,
            "logical_model_calls": 1 + counterfactual_calls + shared_planner_call_allocation,
            **telemetry,
        },
        "metrics": {
            "core_recall": None,
            "learner_recall": None,
            "edge_recall": None,
            "path_recall": None,
            "complete_path_recall_at_2": None,
            "complete_path_recall_at_3": None,
            "graph_completion_rate": None,
            "partial_only_claim_rate": None,
            "claim_conflict_rate": None,
            "strict_evidence_precision": None,
            "graded_evidence_precision": None,
            "contradiction_source_rate": None,
            "distractor_source_rate": None,
            "unassigned_source_rate": None,
        },
    }


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate v3 matrix cases with both successful and failure-adjusted views."""

    grouped: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        grouped.setdefault(result["method"], []).append(result)
    summary = {}
    for method, items in sorted(grouped.items()):
        successful = [item for item in items if item["error"] is None]
        failed = [item for item in items if item["error"] is not None]
        metric_fields = (
            "core_recall",
            "learner_recall",
            "edge_recall",
            "path_recall",
            "complete_path_recall_at_2",
            "complete_path_recall_at_3",
            "graph_completion_rate",
            "partial_only_claim_rate",
            "claim_conflict_rate",
            "strict_evidence_precision",
            "graded_evidence_precision",
            "contradiction_source_rate",
            "distractor_source_rate",
            "unassigned_source_rate",
        )
        successful_means = {
            f"{field}_mean": mean_optional(
                [float(item["metrics"][field]) for item in successful if item["metrics"].get(field) is not None]
            )
            for field in metric_fields
        }
        failure_adjusted_means = {
            f"{field}_failure_adjusted_mean": _failure_adjusted_metric_mean(items, field) for field in metric_fields
        }
        allocated_costs = [
            float(
                item["cost"].get(
                    "allocated_logical_model_calls",
                    item["cost"].get("logical_model_calls", 0.0),
                )
            )
            for item in items
        ]
        coverage_values = [_case_coverage(item) for item in items]
        coverage_per_call = [
            coverage / max(cost, 1.0) for coverage, cost in zip(coverage_values, allocated_costs, strict=True)
        ]
        summary[method] = {
            "cases": len(items),
            "successful": len(successful),
            "failed": len(failed),
            "success_rate": len(successful) / len(items) if items else 0.0,
            **successful_means,
            **failure_adjusted_means,
            "search_calls_mean": mean_optional([float(item["search_calls"]) for item in successful]),
            "retrieval_source_count_mean": mean_optional(
                [float(item["retrieval_source_count"]) for item in successful]
            ),
            "logical_model_calls_mean": mean_optional(
                [float(item["cost"]["logical_model_calls"]) for item in successful]
            ),
            "allocated_logical_model_calls_mean": mean_optional(allocated_costs),
            "total_allocated_logical_model_calls": sum(allocated_costs),
            "coverage_failure_adjusted_mean": mean_optional(coverage_values),
            "coverage_per_allocated_model_call_mean": mean_optional(coverage_per_call),
            "total_prompt_tokens": _sum_optional(items, "prompt_tokens"),
            "total_completion_tokens": _sum_optional(items, "completion_tokens"),
            "total_tokens": _sum_optional(items, "total_tokens"),
            "total_latency_seconds": _sum_optional(items, "latency_seconds"),
        }
    return summary


def _has_learner_gap(item: dict[str, Any]) -> bool:
    visible_gap = item.get("visible_gap")
    return bool(visible_gap and visible_gap.get("learner_requirements"))


def _failure_adjusted_metric_mean(items: list[dict[str, Any]], field: str) -> float | None:
    """Treat an applicable failed attempt as zero, while keeping no-gap learner N/A."""

    values: list[float] = []
    for item in items:
        if item.get("error") is None:
            value = item["metrics"].get(field)
            if value is not None:
                values.append(float(value))
            continue
        if field == "learner_recall" and not _has_learner_gap(item):
            continue
        values.append(0.0)
    return mean_optional(values)


def _case_coverage(item: dict[str, Any]) -> float:
    """Return a failure-adjusted joint core/learner coverage value."""

    if item.get("error") is not None:
        return 0.0
    metrics = item["metrics"]
    core = metrics.get("core_recall")
    learner = metrics.get("learner_recall")
    if core is None:
        return 0.0
    return float(core) if learner is None else (float(core) + float(learner)) / 2.0


def _sum_optional(items: list[dict[str, Any]], field: str) -> float | None:
    """Sum telemetry fields only when at least one case reports the field."""

    values = [item["cost"].get(field) for item in items if item["cost"].get(field) is not None]
    return sum(float(value) for value in values) if values else None


def configured_model(model: str) -> str:
    """Qualify a short model name with the configured provider."""

    provider = os.environ.get("MIMO_PROVIDER", "").strip()
    return f"{provider}/{model}" if provider and "/" not in model else model
