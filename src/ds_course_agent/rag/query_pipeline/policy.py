"""Deterministic execution policies for classified learning intents."""

from __future__ import annotations

from dataclasses import dataclass

from .models import (
    EnrichmentPlan,
    ExecutionMode,
    RetrievalPolicy,
    RouteDecision,
    RouteFamily,
    RouteIntent,
)


@dataclass(frozen=True)
class LearningExecutionPolicy:
    """Execution contract selected after semantic intent classification."""

    execution_mode: ExecutionMode
    retrieval_policy: RetrievalPolicy
    executor_key: str | None
    enrichment: EnrichmentPlan


_LEARNING_POLICIES: dict[RouteIntent, LearningExecutionPolicy] = {
    RouteIntent.CONCEPT_QA: LearningExecutionPolicy(
        ExecutionMode.GROUNDED_GENERATION,
        RetrievalPolicy.REQUIRED,
        "course_rag",
        EnrichmentPlan(map_concepts=True, rewrite_query=True, record_learning_event=True),
    ),
    RouteIntent.COMPARISON: LearningExecutionPolicy(
        ExecutionMode.GROUNDED_GENERATION,
        RetrievalPolicy.REQUIRED,
        "course_rag",
        EnrichmentPlan(map_concepts=True, rewrite_query=True, record_learning_event=True),
    ),
    RouteIntent.FOLLOW_UP: LearningExecutionPolicy(
        ExecutionMode.GROUNDED_GENERATION,
        RetrievalPolicy.REQUIRED,
        "course_rag",
        EnrichmentPlan(map_concepts=True, rewrite_query=True, record_learning_event=True),
    ),
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
    RouteIntent.CODE_REVIEW: LearningExecutionPolicy(
        ExecutionMode.TEACHING_SKILL,
        RetrievalPolicy.DISABLED,
        "code-review",
        EnrichmentPlan(map_concepts=True, record_learning_event=True),
    ),
    RouteIntent.CODE_EXECUTION: LearningExecutionPolicy(
        ExecutionMode.PYTHON_SANDBOX,
        RetrievalPolicy.DISABLED,
        "python_sandbox",
        EnrichmentPlan(map_concepts=True, record_learning_event=True),
    ),
    RouteIntent.LEARNING_PATH: LearningExecutionPolicy(
        ExecutionMode.TEACHING_SKILL,
        RetrievalPolicy.OPTIONAL,
        "learning-path",
        EnrichmentPlan(map_concepts=True, load_learner_state=True),
    ),
    RouteIntent.MISCONCEPTION_REPAIR: LearningExecutionPolicy(
        ExecutionMode.TEACHING_SKILL,
        RetrievalPolicy.REQUIRED,
        "misconception-handling",
        EnrichmentPlan(map_concepts=True, rewrite_query=True),
    ),
    RouteIntent.PERSONALIZED_EXPLANATION: LearningExecutionPolicy(
        ExecutionMode.TEACHING_SKILL,
        RetrievalPolicy.REQUIRED,
        "personalized-explanation",
        EnrichmentPlan(
            map_concepts=True,
            load_learner_state=True,
            rewrite_query=True,
            record_learning_event=True,
        ),
    ),
    RouteIntent.OPEN_LEARNING: LearningExecutionPolicy(
        ExecutionMode.TOOL_AGENT,
        RetrievalPolicy.OPTIONAL,
        "learning_tool_agent",
        EnrichmentPlan(map_concepts=True, record_learning_event=True),
    ),
}


def build_learning_decision(
    intent: RouteIntent,
    *,
    confidence: float,
    reasons: list[str],
    requires_course_grounding: bool = False,
) -> RouteDecision:
    """Resolve a learning intent into an immutable execution policy."""

    policy = _LEARNING_POLICIES[intent]
    if requires_course_grounding and intent in {RouteIntent.CODE_EXAMPLE, RouteIntent.CODE_EXPLANATION}:
        policy = LearningExecutionPolicy(
            ExecutionMode.GROUNDED_GENERATION,
            RetrievalPolicy.REQUIRED,
            "course_rag",
            EnrichmentPlan(map_concepts=True, rewrite_query=True, record_learning_event=True),
        )

    return RouteDecision(
        family=RouteFamily.LEARNING,
        intent=intent,
        execution_mode=policy.execution_mode,
        confidence=confidence,
        reasons=reasons,
        retrieval_policy=policy.retrieval_policy,
        allowed_tools=("course_rag_tool",) if policy.execution_mode is ExecutionMode.TOOL_AGENT else (),
        executor_key=policy.executor_key,
        enrichment=policy.enrichment,
    )


def learning_policy_for(intent: RouteIntent) -> LearningExecutionPolicy:
    """Return the policy for a supported learning intent."""

    return _LEARNING_POLICIES[intent]


__all__ = ["LearningExecutionPolicy", "build_learning_decision", "learning_policy_for"]
