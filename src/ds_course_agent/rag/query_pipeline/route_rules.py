"""Declarative fast-route rules for the bounded teaching agent."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .models import (
    EnrichmentPlan,
    ExecutionMode,
    QueryContext,
    RetrievalPolicy,
    RouteDecision,
    RouteFamily,
    RouteIntent,
)
from .utils import is_datetime_request, is_schedule_request


@dataclass(frozen=True)
class RouteRule:
    """One priority-ordered routing rule with explicit lazy dependencies."""

    priority: int
    name: str
    match_fn: Callable[[QueryContext], bool]
    build_decision: Callable[[QueryContext], RouteDecision]
    requires_skills: bool = False
    requires_concepts: bool = False


def build_route_rules(router: Any) -> tuple[RouteRule, ...]:
    """Build the deterministic fast-rule table.

    Ambiguous fallthrough is resolved by ``QueryRouter``'s semantic learning
    router rather than by a generic all-tools agent.
    """

    rules = [
        RouteRule(1, "boundary_response", _match_boundary_response, _build_boundary_response),
        _bind(router, 10, "current_datetime", _match_current_datetime, _build_datetime_decision),
        _bind(router, 20, "course_schedule", _match_course_schedule, _build_schedule_decision),
        RouteRule(30, "web_research", _match_web_research, _build_web_research),
        RouteRule(40, "code_review", _match_code_review, _build_code_review),
        RouteRule(50, "code_execution", _match_code_execution, _build_code_execution),
        _bind(router, 60, "code_learning", _match_code_learning, _build_code_learning),
        _bind(
            router,
            70,
            "explicit_misconception",
            _match_explicit_misconception,
            _build_explicit_misconception,
            requires_skills=True,
        ),
        _bind(
            router,
            80,
            "learning_path",
            _match_learning_path,
            _build_learning_path,
            requires_skills=True,
        ),
        _bind(
            router,
            90,
            "misconception",
            _match_misconception,
            _build_misconception,
            requires_skills=True,
        ),
        _bind(
            router,
            100,
            "personalized_explanation",
            _match_personalized_explanation,
            _build_personalized_explanation,
            requires_skills=True,
        ),
        _bind(
            router,
            110,
            "grounded_learning",
            _match_grounded_learning,
            _build_grounded_learning,
        ),
    ]
    return tuple(sorted(rules, key=lambda rule: rule.priority))


def _bind(
    router: Any,
    priority: int,
    name: str,
    match_fn: Callable[[Any, QueryContext], bool],
    build_decision: Callable[[Any, QueryContext], RouteDecision],
    *,
    requires_skills: bool = False,
    requires_concepts: bool = False,
) -> RouteRule:
    return RouteRule(
        priority,
        name,
        lambda context: match_fn(router, context),
        lambda context: build_decision(router, context),
        requires_skills=requires_skills,
        requires_concepts=requires_concepts,
    )


def _match_boundary_response(context: QueryContext) -> bool:
    return bool(context.special_case_response)


def _build_boundary_response(context: QueryContext) -> RouteDecision:
    intent = RouteIntent.SMALLTALK if context.scope_category == "smalltalk" else RouteIntent.REFUSAL
    return RouteDecision(
        family=RouteFamily.BOUNDARY,
        intent=intent,
        execution_mode=ExecutionMode.STATIC_RESPONSE,
        confidence=1.0,
        reasons=[f"boundary={context.scope_category or 'special_case'}"],
        retrieval_policy=RetrievalPolicy.DISABLED,
    )


def _match_current_datetime(router: Any, context: QueryContext) -> bool:
    return is_datetime_request(router._normalize(context.normalized_query))


def _build_datetime_decision(router: Any, context: QueryContext) -> RouteDecision:
    del router, context
    return RouteDecision(
        family=RouteFamily.COURSE_SERVICE,
        intent=RouteIntent.CURRENT_DATETIME,
        execution_mode=ExecutionMode.DETERMINISTIC_TOOL,
        confidence=0.95,
        reasons=["检测到时间查询关键词"],
        executor_key="current_datetime_tool",
    )


def _match_course_schedule(router: Any, context: QueryContext) -> bool:
    return is_schedule_request(router._normalize(context.normalized_query))


def _build_schedule_decision(router: Any, context: QueryContext) -> RouteDecision:
    del router, context
    return RouteDecision(
        family=RouteFamily.COURSE_SERVICE,
        intent=RouteIntent.COURSE_SCHEDULE,
        execution_mode=ExecutionMode.DETERMINISTIC_TOOL,
        confidence=0.95,
        reasons=["检测到课程安排查询关键词"],
        retrieval_policy=RetrievalPolicy.OPTIONAL,
        executor_key="course_schedule_tool",
    )


def _match_web_research(context: QueryContext) -> bool:
    return bool(context.web_search_requested)


def _build_web_research(context: QueryContext) -> RouteDecision:
    del context
    return RouteDecision(
        family=RouteFamily.EXTERNAL_RESEARCH,
        intent=RouteIntent.WEB_RESEARCH,
        execution_mode=ExecutionMode.WEB_PIPELINE,
        confidence=1.0,
        reasons=["用户显式开启联网搜索"],
        retrieval_policy=RetrievalPolicy.REQUIRED,
        executor_key="web_search",
    )


def _match_code_review(context: QueryContext) -> bool:
    return "code_review" in context.detected_intents


def _build_code_review(context: QueryContext) -> RouteDecision:
    del context
    return RouteDecision(
        family=RouteFamily.LEARNING,
        intent=RouteIntent.CODE_REVIEW,
        execution_mode=ExecutionMode.TEACHING_SKILL,
        confidence=0.93,
        reasons=["检测到代码审查请求"],
        executor_key="code-review",
        enrichment=EnrichmentPlan(map_concepts=True, record_learning_event=True),
    )


def _match_code_execution(context: QueryContext) -> bool:
    return "python_execution" in context.detected_intents


def _build_code_execution(context: QueryContext) -> RouteDecision:
    del context
    return RouteDecision(
        family=RouteFamily.LEARNING,
        intent=RouteIntent.CODE_EXECUTION,
        execution_mode=ExecutionMode.PYTHON_SANDBOX,
        confidence=0.95,
        reasons=["检测到明确 Python 代码执行请求"],
        executor_key="python_sandbox",
        enrichment=EnrichmentPlan(map_concepts=True, record_learning_event=True),
    )


def _match_code_learning(router: Any, context: QueryContext) -> bool:
    return router._route_code_learning(context) is not None


def _build_code_learning(router: Any, context: QueryContext) -> RouteDecision:
    decision = router._route_code_learning(context)
    if decision is None:
        raise RuntimeError("code-learning rule matched but produced no decision")
    return decision


def _match_explicit_misconception(router: Any, context: QueryContext) -> bool:
    return router._should_use_misconception_skill(context) and router._has_explicit_misconception_signal(context)


def _build_explicit_misconception(router: Any, context: QueryContext) -> RouteDecision:
    return RouteDecision(
        family=RouteFamily.LEARNING,
        intent=RouteIntent.MISCONCEPTION_REPAIR,
        execution_mode=ExecutionMode.TEACHING_SKILL,
        confidence=0.89,
        reasons=router._get_misconception_reasons(context) + ["明确误认知信号"],
        retrieval_policy=RetrievalPolicy.REQUIRED,
        executor_key="misconception-handling",
        enrichment=EnrichmentPlan(map_concepts=True, rewrite_query=True),
    )


def _match_learning_path(router: Any, context: QueryContext) -> bool:
    return router._should_use_learning_path_skill(context)


def _build_learning_path(router: Any, context: QueryContext) -> RouteDecision:
    return RouteDecision(
        family=RouteFamily.LEARNING,
        intent=RouteIntent.LEARNING_PATH,
        execution_mode=ExecutionMode.TEACHING_SKILL,
        confidence=0.90,
        reasons=router._get_learning_path_reasons(context),
        retrieval_policy=RetrievalPolicy.OPTIONAL,
        executor_key="learning-path",
        enrichment=EnrichmentPlan(map_concepts=True, load_learner_state=True),
    )


def _match_misconception(router: Any, context: QueryContext) -> bool:
    return router._should_use_misconception_skill(context)


def _build_misconception(router: Any, context: QueryContext) -> RouteDecision:
    return RouteDecision(
        family=RouteFamily.LEARNING,
        intent=RouteIntent.MISCONCEPTION_REPAIR,
        execution_mode=ExecutionMode.TEACHING_SKILL,
        confidence=0.88,
        reasons=router._get_misconception_reasons(context),
        retrieval_policy=RetrievalPolicy.REQUIRED,
        executor_key="misconception-handling",
        enrichment=EnrichmentPlan(map_concepts=True, rewrite_query=True),
    )


def _match_personalized_explanation(router: Any, context: QueryContext) -> bool:
    return router._should_use_explanation_skill(context)


def _build_personalized_explanation(router: Any, context: QueryContext) -> RouteDecision:
    return RouteDecision(
        family=RouteFamily.LEARNING,
        intent=RouteIntent.PERSONALIZED_EXPLANATION,
        execution_mode=ExecutionMode.TEACHING_SKILL,
        confidence=0.85,
        reasons=router._get_explanation_reasons(context),
        retrieval_policy=RetrievalPolicy.REQUIRED,
        executor_key="personalized-explanation",
        enrichment=EnrichmentPlan(
            map_concepts=True,
            load_learner_state=True,
            rewrite_query=True,
            record_learning_event=True,
        ),
    )


def _match_grounded_learning(router: Any, context: QueryContext) -> bool:
    return router._is_likely_course_question(context)


def _build_grounded_learning(router: Any, context: QueryContext) -> RouteDecision:
    intent = RouteIntent.COMPARISON if "comparison" in context.detected_intents else RouteIntent.CONCEPT_QA
    return RouteDecision(
        family=RouteFamily.LEARNING,
        intent=intent,
        execution_mode=ExecutionMode.GROUNDED_GENERATION,
        confidence=0.80,
        reasons=["课程相关知识问答"],
        retrieval_policy=RetrievalPolicy.REQUIRED,
        executor_key="course_rag",
        enrichment=EnrichmentPlan(map_concepts=True, rewrite_query=True, record_learning_event=True),
    )


__all__ = ["RouteRule", "build_route_rules"]
