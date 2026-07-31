"""Typed QueryPipeline routing-contract tests."""

from __future__ import annotations

import pytest

from ds_course_agent.rag.query_pipeline import (
    EnrichmentPlan,
    ExecutionMode,
    QueryContext,
    RetrievalPolicy,
    RouteDecision,
    RouteFamily,
    RouteIntent,
    RouteState,
    get_preprocessor,
)
from ds_course_agent.rag.query_pipeline.router import QueryRouter


def _context(query: str) -> QueryContext:
    return get_preprocessor(enable_concept_detection=False).process(
        user_input=query,
        session_id="contract-session",
        student_id="contract-student",
        chat_history=[],
    )


def _router() -> QueryRouter:
    return QueryRouter()


def test_route_decision_normalizes_enums_sequences_and_metadata():
    decision = RouteDecision(
        family="learning",
        intent="concept_qa",
        execution_mode="learning_answer",
        confidence=0.9,
        reasons=("课程问答",),
        retrieval_policy="required",
        allowed_tools=[],
        metadata={"source": "test"},
    )

    assert decision.family is RouteFamily.LEARNING
    assert decision.intent is RouteIntent.CONCEPT_QA
    assert decision.execution_mode is ExecutionMode.LEARNING_ANSWER
    assert decision.retrieval_policy is RetrievalPolicy.REQUIRED
    assert decision.allowed_tools == ()
    assert decision.reasons == ["课程问答"]
    assert decision.metadata == {"source": "test"}


def test_route_decision_enforces_structural_tool_gating():
    with pytest.raises(ValueError, match="requires an explicit non-empty"):
        RouteDecision(
            family=RouteFamily.LEARNING,
            intent=RouteIntent.CONCEPT_QA,
            execution_mode=ExecutionMode.TOOL_AGENT,
            confidence=0.5,
        )

    with pytest.raises(ValueError, match="cannot bind generic-agent tools"):
        RouteDecision(
            family=RouteFamily.LEARNING,
            intent=RouteIntent.CODE_EXAMPLE,
            execution_mode=ExecutionMode.DIRECT_MODEL,
            confidence=0.5,
            allowed_tools=("course_rag_tool",),
        )

    decision = RouteDecision(
        family=RouteFamily.LEARNING,
        intent=RouteIntent.CONCEPT_QA,
        execution_mode=ExecutionMode.TOOL_AGENT,
        confidence=0.5,
        allowed_tools=("course_rag_tool",),
    )
    assert decision.allowed_tools == ("course_rag_tool",)


@pytest.mark.parametrize(
    (
        "query",
        "expected_family",
        "expected_intent",
        "expected_mode",
        "expected_policy",
        "expected_executor",
    ),
    [
        (
            "现在几点？",
            RouteFamily.COURSE_SERVICE,
            RouteIntent.CURRENT_DATETIME,
            ExecutionMode.DETERMINISTIC_TOOL,
            RetrievalPolicy.DISABLED,
            "current_datetime_tool",
        ),
        (
            "第三周讲什么内容？",
            RouteFamily.COURSE_SERVICE,
            RouteIntent.COURSE_SCHEDULE,
            ExecutionMode.DETERMINISTIC_TOOL,
            RetrievalPolicy.OPTIONAL,
            "course_schedule_tool",
        ),
        (
            "请运行这段代码并告诉我输出：print(1 + 1)",
            RouteFamily.LEARNING,
            RouteIntent.CODE_EXECUTION,
            ExecutionMode.PYTHON_SANDBOX,
            RetrievalPolicy.DISABLED,
            "python_sandbox",
        ),
        (
            "什么是过拟合？",
            RouteFamily.LEARNING,
            RouteIntent.CONCEPT_QA,
            ExecutionMode.LEARNING_ANSWER,
            RetrievalPolicy.REQUIRED,
            "course_rag",
        ),
        (
            "请用 Python 演示一次交叉验证",
            RouteFamily.LEARNING,
            RouteIntent.CODE_EXAMPLE,
            ExecutionMode.DIRECT_MODEL,
            RetrievalPolicy.OPTIONAL,
            None,
        ),
    ],
)
def test_fast_router_populates_the_typed_contract(
    query,
    expected_family,
    expected_intent,
    expected_mode,
    expected_policy,
    expected_executor,
):
    router = _router()
    decision = router.route(_context(query))

    assert decision.family is expected_family
    assert decision.intent is expected_intent
    assert decision.execution_mode is expected_mode
    assert decision.retrieval_policy is expected_policy
    assert decision.executor_key == expected_executor
    assert decision.allowed_tools == ()


def test_rule_table_is_priority_ordered_and_has_clarification_fallback():
    router = _router()
    rules = router.rules

    assert [rule.priority for rule in rules] == sorted(rule.priority for rule in rules)
    assert [rule.name for rule in rules[:4]] == [
        "boundary_response",
        "current_datetime",
        "course_schedule",
        "web_research",
    ]
    assert rules[-1].name == "clarification"
    assert {rule.name for rule in rules} >= {
        "code_review",
        "code_execution",
        "code_learning",
        "learning_path",
        "misconception",
        "personalized_explanation",
    }


def test_boundary_and_course_service_precede_explicit_web_research():
    router = _router()

    boundary = _context("现在几点？")
    boundary.special_case_response = "固定边界响应"
    boundary.scope_category = "off_topic"
    boundary.web_search_requested = True
    decision = router.route(boundary)
    assert (
        decision.family,
        decision.intent,
        decision.execution_mode,
    ) == (
        RouteFamily.BOUNDARY,
        RouteIntent.REFUSAL,
        ExecutionMode.STATIC_RESPONSE,
    )

    service = _context("现在几点？")
    service.web_search_requested = True
    decision = router.route(service)
    assert (
        decision.family,
        decision.intent,
        decision.execution_mode,
    ) == (
        RouteFamily.COURSE_SERVICE,
        RouteIntent.CURRENT_DATETIME,
        ExecutionMode.DETERMINISTIC_TOOL,
    )


def test_web_research_is_explicit_and_has_no_generic_agent_tools():
    router = _router()
    context = _context("搜索最新的数据科学教学资源")
    context.web_search_requested = True

    decision = router.route(context)

    assert decision.family is RouteFamily.EXTERNAL_RESEARCH
    assert decision.intent is RouteIntent.WEB_RESEARCH
    assert decision.execution_mode is ExecutionMode.WEB_PIPELINE
    assert decision.retrieval_policy is RetrievalPolicy.REQUIRED
    assert decision.allowed_tools == ()


def test_learning_answer_is_direct_and_tool_free():
    decision = _router().route(_context("监督学习和无监督学习有什么区别？"))
    assert decision.family is RouteFamily.LEARNING
    assert decision.intent is RouteIntent.COMPARISON
    assert decision.execution_mode is ExecutionMode.LEARNING_ANSWER
    assert decision.retrieval_policy is RetrievalPolicy.REQUIRED
    assert decision.allowed_tools == ()
    assert decision.style_hint.value == "comparison"


def test_ambiguous_boundary_is_static_and_tool_free():
    context = _context("这个怎么弄")
    decision = _router().route(context)
    assert decision.family is RouteFamily.BOUNDARY
    assert decision.intent is RouteIntent.NEEDS_CLARIFICATION
    assert decision.execution_mode is ExecutionMode.STATIC_RESPONSE
    assert decision.retrieval_policy is RetrievalPolicy.DISABLED
    assert decision.allowed_tools == ()
    assert context.special_case_response


def _route_state(decision: RouteDecision) -> RouteState:
    context = QueryContext(
        original_query="q",
        normalized_query="q",
        session_id="s",
        student_id="stu",
        chat_history=[],
    )
    return RouteState(
        context=context,
        decision=decision,
        chat_history=[],
        student_id="stu",
        session_id="s",
    )


def _make_gated_service(monkeypatch):
    from ds_course_agent.rag.agent import AgentService
    from ds_course_agent.tools.registry import get_rag_tool_registry

    service = object.__new__(AgentService)
    service.tool_registry = get_rag_tool_registry()
    service.llm = object()
    service.agent = ("default-agent", ())
    service._agent_cache_by_tools = {}
    service.chat = lambda *args, **kwargs: None
    service.direct_chat = lambda *args, **kwargs: None

    def fake_create_agent(tools=None):
        names = tuple(getattr(tool, "name", str(tool)) for tool in (tools or []))
        return ("subset-agent", names)

    monkeypatch.setattr(service, "_create_agent", fake_create_agent)
    return service


def test_generic_handler_direct_model_binds_no_tools(monkeypatch):
    from ds_course_agent.rag.route_handlers import GenericAgentRouteHandler

    service = _make_gated_service(monkeypatch)
    decision = RouteDecision(
        family=RouteFamily.LEARNING,
        intent=RouteIntent.CODE_EXAMPLE,
        execution_mode=ExecutionMode.DIRECT_MODEL,
        confidence=0.8,
        retrieval_policy=RetrievalPolicy.OPTIONAL,
    )

    chat_fn, _context, direct_llm, graph_agent = GenericAgentRouteHandler()._chat_callable_and_context(
        service,
        _route_state(decision),
        "",
    )

    assert chat_fn is service.direct_chat
    assert direct_llm is True
    assert graph_agent is None


def test_generic_handler_tool_agent_binds_exact_allowlist(monkeypatch):
    from ds_course_agent.rag.route_handlers import GenericAgentRouteHandler

    service = _make_gated_service(monkeypatch)
    decision = RouteDecision(
        family=RouteFamily.LEARNING,
        intent=RouteIntent.CONCEPT_QA,
        execution_mode=ExecutionMode.TOOL_AGENT,
        confidence=0.8,
        retrieval_policy=RetrievalPolicy.OPTIONAL,
        allowed_tools=("course_rag_tool",),
    )

    _chat_fn, _context, direct_llm, graph_agent = GenericAgentRouteHandler()._chat_callable_and_context(
        service,
        _route_state(decision),
        "",
    )

    assert direct_llm is False
    assert graph_agent == ("subset-agent", ("course_rag_tool",))
    assert "python_exec_tool" not in graph_agent[1]


def test_route_state_carries_decision_and_enrichment_without_metadata_control_signals():
    context = _context("什么是过拟合？")
    decision = RouteDecision(
        family=RouteFamily.LEARNING,
        intent=RouteIntent.CONCEPT_QA,
        execution_mode=ExecutionMode.LEARNING_ANSWER,
        confidence=0.8,
        retrieval_policy=RetrievalPolicy.REQUIRED,
        enrichment=EnrichmentPlan(
            map_concepts=True,
            rewrite_query=True,
            record_learning_event=True,
        ),
    )
    state = _route_state(decision)
    state.context = context

    assert state.decision.enrichment.map_concepts is True
    assert state.decision.enrichment.rewrite_query is True
    assert state.decision.enrichment.record_learning_event is True
    assert "required_tools" not in state.decision.metadata
    assert "direct_llm_answer" not in state.decision.metadata
    assert "autonomous_tool_choice" not in state.decision.metadata
