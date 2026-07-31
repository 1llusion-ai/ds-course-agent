"""Deterministic execution policies for explicit direct-model learning intents."""

from __future__ import annotations

from dataclasses import dataclass

from .models import (
    EnrichmentPlan,
    ExecutionMode,
    LearningStyleHint,
    RetrievalPolicy,
    RouteDecision,
    RouteFamily,
    RouteIntent,
)


@dataclass(frozen=True)
class LearningExecutionPolicy:
    """Execution contract selected from a deterministic learning intent."""

    execution_mode: ExecutionMode
    retrieval_policy: RetrievalPolicy
    executor_key: str | None
    enrichment: EnrichmentPlan


_LEARNING_POLICIES: dict[RouteIntent, LearningExecutionPolicy] = {
    RouteIntent.CODE_EXAMPLE: LearningExecutionPolicy(
        ExecutionMode.DIRECT_MODEL,
        RetrievalPolicy.OPTIONAL,
        None,
        EnrichmentPlan(map_concepts=True, record_learning_event=True),
    ),
    RouteIntent.CODE_EXPLANATION: LearningExecutionPolicy(
        ExecutionMode.DIRECT_MODEL,
        RetrievalPolicy.OPTIONAL,
        None,
        EnrichmentPlan(map_concepts=True, record_learning_event=True),
    ),
}


def learning_style_hint_for(context, intent: RouteIntent) -> LearningStyleHint:
    """Return a non-authoritative presentation hint from deterministic signals."""

    if intent is RouteIntent.CODE_EXAMPLE:
        return LearningStyleHint.CODE_EXAMPLE
    if intent is RouteIntent.CODE_EXPLANATION:
        return LearningStyleHint.CODE_EXPLANATION
    if "comparison" in set(context.detected_intents or []):
        return LearningStyleHint.COMPARISON
    if context.is_followup:
        return LearningStyleHint.FOLLOW_UP
    if intent is RouteIntent.CONCEPT_QA:
        return LearningStyleHint.CONCEPT_EXPLANATION
    return LearningStyleHint.GENERAL_LEARNING


def build_learning_decision(
    intent: RouteIntent,
    *,
    confidence: float,
    reasons: list[str],
    style_hint: LearningStyleHint | None = None,
) -> RouteDecision:
    """Resolve a learning intent into an immutable execution policy."""

    policy = _LEARNING_POLICIES[intent]
    return RouteDecision(
        family=RouteFamily.LEARNING,
        intent=intent,
        execution_mode=policy.execution_mode,
        confidence=confidence,
        reasons=reasons,
        retrieval_policy=policy.retrieval_policy,
        style_hint=style_hint or LearningStyleHint.GENERAL_LEARNING,
        executor_key=policy.executor_key,
        enrichment=policy.enrichment,
    )


def learning_policy_for(intent: RouteIntent) -> LearningExecutionPolicy:
    """Return the policy for a supported learning intent."""

    return _LEARNING_POLICIES[intent]


__all__ = [
    "LearningExecutionPolicy",
    "build_learning_decision",
    "learning_policy_for",
    "learning_style_hint_for",
]
