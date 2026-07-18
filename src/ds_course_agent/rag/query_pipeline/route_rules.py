"""Declarative route rule table for QueryRouter."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .models import QueryContext, RetrievalPolicy, RouteDecision, RouteType
from .utils import is_datetime_request, is_schedule_request


@dataclass(frozen=True)
class RouteRule:
    """声明式路由规则：显式 priority 表达原先 if/elif 的顺序语义。

    富化是规则求值的惰性依赖，分两个 memoized 阶段：

    - ``requires_skills``：match_fn 依赖 skill_candidate_keys（廉价的 keyword
      skill_select）。explicit_misconception/learning_path/misconception/explanation
      需要它。trigger 后任何后续规则复用同一结果。
    - ``requires_concepts``：match_fn 依赖 detected_concepts/rewrite/profile
      （昂贵的 concept_map + rewrite + profile_load）。explanation/
      rewritten_followup/grounded_rag 需要它。

    高置信 fast-path 规则（二者皆 False）在富化前即可命中并短路，因此
    datetime/schedule/code/python 等查询不触发任何富化；autonomous(p60) 与纯 skill
    路由只触发廉价的 skill_select，不跑 concept_map。这是「富化成为规则求值的惰性
    依赖」的闭合点，恢复旧 prepass 对 code/example/demo 的快速路径。
    """

    priority: int
    name: str
    match_fn: Callable[[QueryContext], bool]
    build_decision: Callable[[QueryContext], RouteDecision]
    requires_skills: bool = False
    requires_concepts: bool = False


def build_route_rules(router: Any) -> tuple[RouteRule, ...]:
    """Build the priority-ordered route rule table for a QueryRouter instance."""
    rules = [
        # 外部准备阶段的强制分流先落入同一张表，避免主干再长分支。
        RouteRule(1, "special_case", _match_special_case, _build_special_case_decision),
        RouteRule(2, "web_search", _match_web_search, _build_web_search_decision),
        # 明确代码审查要先于 python_exec，避免 pasted code 被盲目运行。
        RouteRule(10, "code_review", _match_code_review, _build_code_review_decision),
        # 执行请求要先于系统工具，避免代码文本里的“今天/第3周”误触发。
        RouteRule(20, "python_execution", _match_python_execution, _build_python_exec_decision),
        _bind(router, 30, "current_datetime", _match_current_datetime, _build_datetime_decision),
        _bind(router, 40, "course_schedule", _match_course_schedule, _build_schedule_decision),
        # 明确错误前提优先于 autonomous tool choice，保住教学纠偏路径。
        # explicit_misconception 是首个依赖富化的规则：任何未被 fast-path 命中
        # 的查询都会在这里触发一次廉价的 skill_select；concept_map 仅在 p90+
        # 的概念规则才触发，因此 autonomous(p60)/skill 路由不跑 concept_map。
        _bind(
            router,
            50,
            "explicit_misconception",
            _match_explicit_misconception,
            _build_explicit_misconception,
            requires_skills=True,
        ),
        # 代码/示例/实现类模糊请求不强制 RAG，由通用 agent 自主选择工具。
        _bind(router, 60, "autonomous_tool_choice", _match_autonomous_tool_choice, _build_autonomous_tool_choice),
        _bind(
            router,
            70,
            "learning_path_skill",
            _match_learning_path,
            _build_learning_path_decision,
            requires_skills=True,
        ),
        _bind(
            router,
            80,
            "misconception_skill",
            _match_misconception,
            _build_misconception_decision,
            requires_skills=True,
        ),
        _bind(
            router,
            90,
            "personalized_explanation_skill",
            _match_personalized_explanation,
            _build_explanation_decision,
            requires_skills=True,
            requires_concepts=True,
        ),
        _bind(
            router,
            100,
            "rewritten_followup",
            _match_rewritten_followup,
            _build_rewrite_decision,
            requires_concepts=True,
        ),
        _bind(
            router,
            110,
            "grounded_rag",
            _match_grounded_rag,
            _build_grounded_rag_decision,
            requires_concepts=True,
        ),
        RouteRule(1000, "generic_agent_fallback", _match_always, _build_generic_decision),
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


def _match_special_case(context: QueryContext) -> bool:
    return bool(context.special_case_response)


def _build_special_case_decision(context: QueryContext) -> RouteDecision:
    return RouteDecision(
        route=RouteType.GENERIC_AGENT,
        confidence=1.0,
        reasons=["特殊问候/致谢/范围保护响应"],
        allowed_tools=[],
        retrieval_policy=RetrievalPolicy.DISABLED,
        direct_llm_answer=True,
        direct_llm_reason="special_case_response",
    )


def _match_web_search(context: QueryContext) -> bool:
    return bool(context.web_search_requested)


def _build_web_search_decision(context: QueryContext) -> RouteDecision:
    return RouteDecision(
        route=RouteType.WEB_SEARCH,
        confidence=1.0,
        reasons=["用户显式开启联网搜索"],
        allowed_tools=["web_search_tool"],
        required_tools=["web_search_tool"],
        retrieval_policy=RetrievalPolicy.REQUIRED,
    )


def _match_code_review(context: QueryContext) -> bool:
    return "code_review" in context.detected_intents


def _build_code_review_decision(context: QueryContext) -> RouteDecision:
    return RouteDecision(
        route=RouteType.CODE_REVIEW,
        confidence=0.93,
        reasons=["检测到代码审查请求"],
        skill_name="code-review",
        allowed_tools=[],
        retrieval_policy=RetrievalPolicy.DISABLED,
    )


def _match_python_execution(context: QueryContext) -> bool:
    return "python_execution" in context.detected_intents


def _build_python_exec_decision(context: QueryContext) -> RouteDecision:
    return RouteDecision(
        route=RouteType.PYTHON_EXEC,
        confidence=0.95,
        reasons=["检测到明确 Python 代码执行请求"],
        allowed_tools=["python_exec_tool"],
        required_tools=["python_exec_tool"],
        retrieval_policy=RetrievalPolicy.DISABLED,
    )


def _match_current_datetime(router: Any, context: QueryContext) -> bool:
    return is_datetime_request(router._normalize(context.normalized_query))


def _build_datetime_decision(router: Any, context: QueryContext) -> RouteDecision:
    return RouteDecision(
        route=RouteType.CURRENT_DATETIME,
        confidence=0.95,
        reasons=["检测到时间查询关键词"],
        allowed_tools=["current_datetime_tool"],
        required_tools=["current_datetime_tool"],
        retrieval_policy=RetrievalPolicy.DISABLED,
    )


def _match_course_schedule(router: Any, context: QueryContext) -> bool:
    return is_schedule_request(router._normalize(context.normalized_query))


def _build_schedule_decision(router: Any, context: QueryContext) -> RouteDecision:
    return RouteDecision(
        route=RouteType.COURSE_SCHEDULE,
        confidence=0.95,
        reasons=["检测到课程安排查询关键词"],
        allowed_tools=["course_schedule_tool"],
        required_tools=["course_schedule_tool"],
        retrieval_policy=RetrievalPolicy.OPTIONAL,
    )


def _match_explicit_misconception(router: Any, context: QueryContext) -> bool:
    return router._should_use_misconception_skill(context) and router._has_explicit_misconception_signal(context)


def _build_explicit_misconception(router: Any, context: QueryContext) -> RouteDecision:
    return RouteDecision(
        route=RouteType.MISCONCEPTION_SKILL,
        confidence=0.89,
        reasons=router._get_misconception_reasons(context) + ["明确误认知信号优先于 autonomous tool choice"],
        skill_name="misconception-handling",
        allowed_tools=["course_rag_tool"],
        retrieval_policy=RetrievalPolicy.REQUIRED,
        fallback_route=RouteType.GROUNDED_RAG,
    )


def _match_autonomous_tool_choice(router: Any, context: QueryContext) -> bool:
    return router._route_autonomous_tool_choice(context) is not None


def _build_autonomous_tool_choice(router: Any, context: QueryContext) -> RouteDecision:
    decision = router._route_autonomous_tool_choice(context)
    if decision is None:
        raise RuntimeError("autonomous tool choice rule matched but did not build a decision")
    return decision


def _match_learning_path(router: Any, context: QueryContext) -> bool:
    return router._should_use_learning_path_skill(context)


def _build_learning_path_decision(router: Any, context: QueryContext) -> RouteDecision:
    return RouteDecision(
        route=RouteType.LEARNING_PATH_SKILL,
        confidence=0.90,
        reasons=router._get_learning_path_reasons(context),
        skill_name="learning-path",
        allowed_tools=["course_rag_tool"],
        retrieval_policy=RetrievalPolicy.OPTIONAL,
        fallback_route=RouteType.GROUNDED_RAG,
    )


def _match_misconception(router: Any, context: QueryContext) -> bool:
    return router._should_use_misconception_skill(context)


def _build_misconception_decision(router: Any, context: QueryContext) -> RouteDecision:
    return RouteDecision(
        route=RouteType.MISCONCEPTION_SKILL,
        confidence=0.88,
        reasons=router._get_misconception_reasons(context),
        skill_name="misconception-handling",
        allowed_tools=["course_rag_tool"],
        retrieval_policy=RetrievalPolicy.REQUIRED,
        fallback_route=RouteType.GROUNDED_RAG,
    )


def _match_personalized_explanation(router: Any, context: QueryContext) -> bool:
    return router._should_use_explanation_skill(context)


def _build_explanation_decision(router: Any, context: QueryContext) -> RouteDecision:
    return RouteDecision(
        route=RouteType.PERSONALIZED_EXPLANATION_SKILL,
        confidence=0.85,
        reasons=router._get_explanation_reasons(context),
        skill_name="personalized-explanation",
        allowed_tools=["course_rag_tool"],
        retrieval_policy=RetrievalPolicy.REQUIRED,
        fallback_route=RouteType.GROUNDED_RAG,
    )


def _match_rewritten_followup(router: Any, context: QueryContext) -> bool:
    return router._route_rewritten_followup(context) is not None


def _build_rewrite_decision(router: Any, context: QueryContext) -> RouteDecision:
    decision = router._route_rewritten_followup(context)
    if decision is None:
        raise RuntimeError("rewrite follow-up rule matched but did not build a decision")
    return decision


def _match_grounded_rag(router: Any, context: QueryContext) -> bool:
    return router._is_likely_course_question(context)


def _build_grounded_rag_decision(router: Any, context: QueryContext) -> RouteDecision:
    return RouteDecision(
        route=RouteType.GROUNDED_RAG,
        confidence=0.80,
        reasons=["课程相关知识问答"],
        allowed_tools=["course_rag_tool"],
        retrieval_policy=RetrievalPolicy.REQUIRED,
        fallback_route=RouteType.GENERIC_AGENT,
    )


def _match_always(context: QueryContext) -> bool:
    return True


def _build_generic_decision(context: QueryContext) -> RouteDecision:
    return RouteDecision(
        route=RouteType.GENERIC_AGENT,
        confidence=0.60,
        reasons=["未匹配到特定路由，使用通用 agent"],
        allowed_tools=[
            "course_rag_tool",
            "python_exec_tool",
            "course_schedule_tool",
            "current_datetime_tool",
        ],
        retrieval_policy=RetrievalPolicy.OPTIONAL,
    )
