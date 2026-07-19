"""QueryPipeline phase-1 contract tests."""

from __future__ import annotations

import pytest

from ds_course_agent.rag.query_pipeline import (
    QueryContext,
    RetrievalPolicy,
    RouteDecision,
    RouteState,
    RouteType,
    get_preprocessor,
    get_router,
)


def _context(query: str) -> QueryContext:
    return get_preprocessor(enable_concept_detection=False).process(
        user_input=query,
        session_id="contract-session",
        student_id="contract-student",
        chat_history=[],
    )


def test_route_decision_normalizes_retrieval_policy_and_tool_contracts():
    """RouteDecision exposes typed policy and allowed_tools, not only metadata hints."""
    decision = RouteDecision(
        route=RouteType.CURRENT_DATETIME,
        confidence=0.9,
        required_tools=["current_datetime_tool"],
        retrieval_policy="disabled",
    )

    assert decision.retrieval_policy is RetrievalPolicy.DISABLED
    assert decision.retrieval_policy == "disabled"
    assert decision.allowed_tools == ["current_datetime_tool"]
    assert decision.required_tools == ["current_datetime_tool"]


@pytest.mark.parametrize(
    ("query", "expected_route", "expected_policy", "expected_allowed_tools"),
    [
        ("现在几点？", RouteType.CURRENT_DATETIME, RetrievalPolicy.DISABLED, ["current_datetime_tool"]),
        ("第三周讲什么内容？", RouteType.COURSE_SCHEDULE, RetrievalPolicy.OPTIONAL, ["course_schedule_tool"]),
        (
            "请运行这段代码并告诉我输出：print(1 + 1)",
            RouteType.PYTHON_EXEC,
            RetrievalPolicy.DISABLED,
            ["python_exec_tool"],
        ),
        ("什么是过拟合？", RouteType.GROUNDED_RAG, RetrievalPolicy.REQUIRED, ["course_rag_tool"]),
    ],
)
def test_router_populates_route_decision_contract_fields(
    query: str,
    expected_route: RouteType,
    expected_policy: RetrievalPolicy,
    expected_allowed_tools: list[str],
):
    decision = get_router().route(_context(query))

    assert decision.route == expected_route
    assert decision.retrieval_policy is expected_policy
    assert decision.allowed_tools == expected_allowed_tools
    assert set(decision.required_tools).issubset(decision.allowed_tools)


def test_autonomous_and_direct_generic_routes_are_type_signaled():
    router = get_router()

    autonomous_context = _context("帮我解析这段代码在做什么：\n```python\nprint(1 + 1)\n```")
    autonomous_decision = router.route(autonomous_context)
    assert autonomous_decision.route == RouteType.GENERIC_AGENT
    assert autonomous_decision.autonomous_tool_choice is True
    assert autonomous_decision.direct_llm_answer is False
    assert autonomous_decision.allowed_tools == [
        "course_rag_tool",
        "python_exec_tool",
        "course_schedule_tool",
        "current_datetime_tool",
    ]

    direct_context = _context("请用 Python 演示一次交叉验证")
    direct_decision = router.route(direct_context)
    assert direct_decision.route == RouteType.GENERIC_AGENT
    assert direct_decision.direct_llm_answer is True
    assert direct_decision.direct_llm_reason == "code_example_without_execution"
    assert direct_decision.autonomous_tool_choice is False
    assert direct_decision.allowed_tools == []


def test_router_uses_priority_ordered_rule_table_with_fallback():
    rules = get_router().rules

    assert [rule.priority for rule in rules] == sorted(rule.priority for rule in rules)
    assert [rule.name for rule in rules[:2]] == ["special_case", "web_search"]
    assert rules[-1].name == "generic_agent_fallback"
    assert {rule.name for rule in rules} >= {
        "current_datetime",
        "course_schedule",
        "learning_path_skill",
        "grounded_rag",
    }


@pytest.mark.parametrize(
    ("set_signal", "expected_route", "expected_policy", "expected_allowed_tools"),
    [
        (
            lambda ctx: setattr(ctx, "special_case_response", "你好，我是课程助教。"),
            RouteType.GENERIC_AGENT,
            RetrievalPolicy.DISABLED,
            [],
        ),
        (
            lambda ctx: setattr(ctx, "web_search_requested", True),
            RouteType.WEB_SEARCH,
            RetrievalPolicy.REQUIRED,
            ["web_search_tool"],
        ),
    ],
)
def test_router_table_contains_explicit_fast_path_rules(
    set_signal,
    expected_route: RouteType,
    expected_policy: RetrievalPolicy,
    expected_allowed_tools: list[str],
):
    # 控制信号是 QueryContext 的 typed field（Contract 2），不再走 metadata。
    context = _context("现在几点？")
    set_signal(context)

    decision = get_router().route(context)

    assert decision.route == expected_route
    assert decision.retrieval_policy is expected_policy
    assert decision.allowed_tools == expected_allowed_tools


def test_route_state_carries_route_decision_fields_without_metadata_contracts():
    context = _context("现在几点？")
    decision = get_router().route(context)
    state = RouteState(
        context=context,
        decision=decision,
        chat_history=context.chat_history,
        student_id=context.student_id,
        session_id=context.session_id,
    )

    assert state.context is context
    assert state.decision.allowed_tools == ["current_datetime_tool"]
    assert state.decision.retrieval_policy is RetrievalPolicy.DISABLED
    assert state.skill_candidate_keys == set()


# ---------------------------------------------------------------------------
# Production-pinning invariants (T2/T4/T5 + tool_gating observability).
#
# These drive the real QueryPipeline.prepare / GenericAgentRouteHandler paths
# (not the router in isolation) so they fail the moment a fast-path slips back
# into an AgentService early-return or the tool gate stops being structural.
# ---------------------------------------------------------------------------


def _make_service(monkeypatch, *, chat_history=None):
    """Minimal AgentService that runs the full QueryPipeline.prepare path offline.

    Mirrors the patches used by TestAgentRouteSharing so history/memory/concept/
    skill/learning deps are stubbed without touching the router or scope guard.
    """
    from ds_course_agent.rag.agent import AgentService
    from ds_course_agent.rag.profile_models import StudentProfile

    service = object.__new__(AgentService)
    service.skill_loader = None

    class FakeHistory:
        def __init__(self):
            self.messages = list(chat_history or [])

    class FakeMemory:
        def get_profile(self, student_id):
            return StudentProfile(student_id=student_id)

    monkeypatch.setattr("ds_course_agent.shared.history.get_history", lambda session_id: FakeHistory())
    monkeypatch.setattr("ds_course_agent.rag.agent.get_memory_core", lambda: FakeMemory())
    monkeypatch.setattr("ds_course_agent.rag.agent.map_question_to_concepts", lambda question, top_k=3: [])
    monkeypatch.setattr(service, "_handle_special_case", lambda question: None)
    monkeypatch.setattr(service, "_select_skill_candidates", lambda question: set())
    monkeypatch.setattr(service, "_record_learning_events", lambda **kwargs: None)
    return service


def _spy_router_route(monkeypatch, calls):
    """Wrap the router singleton's route() to count invocations per turn."""
    router = get_router()
    orig_route = router.route

    def spy_route(context, *, enricher=None):
        calls["route"] += 1
        return orig_route(context, enricher=enricher)

    monkeypatch.setattr(router, "route", spy_route)


def test_t5_fast_path_routes_through_rule_table_and_skips_enrichment(monkeypatch):
    """T5: datetime fast-path 经规则表（router==1）且不触发概念富化（concept_map==0）。"""
    service = _make_service(monkeypatch)
    calls = {"route": 0, "concept_map": 0}
    _spy_router_route(monkeypatch, calls)

    def spy_concept_map(question, top_k=3):
        calls["concept_map"] += 1
        return []

    monkeypatch.setattr("ds_course_agent.rag.agent.map_question_to_concepts", spy_concept_map)

    state = service._prepare_query_route("现在几点？", "session-t5a", "student-t5a")

    assert state.decision.route is RouteType.CURRENT_DATETIME
    assert calls["route"] == 1  # 通过规则表，而非 agent.py early-return（否则为 0）
    assert calls["concept_map"] == 0  # fast-path 短路，富化不执行
    assert state.context.fast_path is True


def test_t5_course_question_enriches_once_and_routes_once(monkeypatch):
    """T5: 课程问答富化恰好一次、router 只跑一次（惰性富化非第二趟路由）。"""
    service = _make_service(monkeypatch)
    calls = {"route": 0, "concept_map": 0}
    _spy_router_route(monkeypatch, calls)

    def spy_concept_map(question, top_k=3):
        calls["concept_map"] += 1
        return []

    monkeypatch.setattr("ds_course_agent.rag.agent.map_question_to_concepts", spy_concept_map)

    state = service._prepare_query_route("什么是过拟合？", "session-t5b", "student-t5b")

    assert state.decision.route is RouteType.GROUNDED_RAG
    assert calls["route"] == 1
    assert calls["concept_map"] == 1
    assert state.context.fast_path is False


def _make_gated_service(monkeypatch):
    """AgentService with a real tool_registry and sentinel agents.

    Lets _agent_for_tools build real subset bindings (via the registry) without
    an LLM, by replacing _create_agent with a sentinel that records bound names.
    """
    from ds_course_agent.rag.agent import AgentService
    from ds_course_agent.tools.registry import get_rag_tool_registry

    service = object.__new__(AgentService)
    service.tool_registry = get_rag_tool_registry()
    service.llm = object()  # truthy: _agent_for_tools 不走 fallback
    service.agent = ("default-agent", ())  # sentinel default agent
    service._agent_cache_by_tools = {}
    service.chat = lambda *a, **k: None
    service.direct_chat = lambda *a, **k: None

    def fake_create_agent(tools=None):
        names = tuple(getattr(t, "name", str(t)) for t in (tools or []))
        return ("subset-agent", names)

    monkeypatch.setattr(service, "_create_agent", fake_create_agent)
    return service


def _route_state(*, route, allowed_tools=None, retrieval_policy="optional", direct_llm_answer=False):
    decision = RouteDecision(
        route=route,
        confidence=0.5,
        allowed_tools=allowed_tools if allowed_tools is not None else [],
        retrieval_policy=retrieval_policy,
        direct_llm_answer=direct_llm_answer,
    )
    context = QueryContext(
        original_query="q",
        normalized_query="q",
        session_id="s",
        student_id="stu",
        chat_history=[],
    )
    return RouteState(context=context, decision=decision, chat_history=[], student_id="stu", session_id="s")


def _bound_tool_names(graph_agent):
    """Extract tool names recorded by the sentinel subset agent."""
    if graph_agent is None:
        return set()
    return set(graph_agent[1])


def test_t2_subset_agent_binds_exactly_allowed_tools(monkeypatch):
    """T2: _agent_for_tools 绑定的工具集 == allowed_tools（子集，不含未授权工具）。"""
    service = _make_gated_service(monkeypatch)

    agent = service._agent_for_tools(["course_rag_tool"])
    assert _bound_tool_names(agent) == {"course_rag_tool"}
    assert "python_exec_tool" not in _bound_tool_names(agent)

    # 缓存：同名子集返回同一实例
    assert service._agent_for_tools(["course_rag_tool"]) is agent

    # 多工具子集仍精确匹配
    multi = service._agent_for_tools(["course_rag_tool", "current_datetime_tool"])
    assert _bound_tool_names(multi) == {"course_rag_tool", "current_datetime_tool"}


def test_t4_subset_gating_excludes_python_exec_sync_and_stream(monkeypatch):
    """T4: 子集未绑 python_exec_tool 时门控排除它；sync/stream 共享同一闭合点。"""
    from ds_course_agent.rag.route_handlers import GenericAgentRouteHandler

    service = _make_gated_service(monkeypatch)
    handler = GenericAgentRouteHandler()

    # allowed_tools=[course_rag_tool]：选 subset agent（非默认），python_exec 未绑
    state = _route_state(route=RouteType.GENERIC_AGENT, allowed_tools=["course_rag_tool"])
    _chat_fn, _ctx, direct_llm, graph_agent = handler._chat_callable_and_context(service, state, "")
    assert graph_agent is not None
    assert graph_agent is not service.agent  # subset，不是默认全工具 agent
    assert direct_llm is False
    assert "python_exec_tool" not in _bound_tool_names(graph_agent)

    # allowed_tools==[]：直连 LLM，不绑任何工具 agent（sync 与 stream 同路径）
    state_empty = _route_state(route=RouteType.GENERIC_AGENT, allowed_tools=[])
    state_empty.decision.direct_llm_answer = True
    _chat_fn2, _ctx2, direct_llm2, graph_agent2 = handler._chat_callable_and_context(service, state_empty, "")
    assert graph_agent2 is None
    assert direct_llm2 is True


def test_tool_gating_trace_records_route_allowed_tools_and_policy(monkeypatch):
    """Task 1.2: agent.tool_gating trace 记录 route/allowed_tools/policy（none|allowlist|default）。"""
    from ds_course_agent.rag.query_trace import begin_query_trace, end_query_trace
    from ds_course_agent.rag.route_handlers import GenericAgentRouteHandler

    service = _make_gated_service(monkeypatch)
    handler = GenericAgentRouteHandler()

    token = begin_query_trace({"t": "gating"})

    # subset → allowlist
    handler._chat_callable_and_context(
        service, _route_state(route=RouteType.GENERIC_AGENT, allowed_tools=["course_rag_tool"]), ""
    )
    # [] + direct → none
    state_empty = _route_state(route=RouteType.GENERIC_AGENT, allowed_tools=[])
    state_empty.decision.direct_llm_answer = True
    handler._chat_callable_and_context(service, state_empty, "")

    trace = end_query_trace(token)

    gating = [ev["data"] for ev in trace["events"] if ev["stage"] == "agent.tool_gating"]
    policies = {g["policy"] for g in gating}
    assert "allowlist" in policies
    assert "none" in policies
    for payload in gating:
        assert "route" in payload
        assert "allowed_tools" in payload


def test_t3_empty_allowed_tools_routes_to_direct_chat_without_direct_llm_flag(monkeypatch):
    """T3: allowed_tools==[] 即便 direct_llm_answer=False 也必须走 direct_chat（[] 本身物理保证无工具）。"""
    from ds_course_agent.rag.route_handlers import GenericAgentRouteHandler

    service = _make_gated_service(monkeypatch)
    handler = GenericAgentRouteHandler()

    # [] + direct_llm_answer=False：仍走 direct_chat（门控由 [] 驱动，非 direct_llm_answer）
    state = _route_state(route=RouteType.GENERIC_AGENT, allowed_tools=[], direct_llm_answer=False)
    _chat_fn, _ctx, direct_llm, graph_agent = handler._chat_callable_and_context(service, state, "")
    assert graph_agent is None
    assert direct_llm is True


def test_t3_subset_agent_fails_closed_when_deps_missing():
    """Contract 3: 非空 allowlist 缺 llm/tool_registry 时 fail closed（raise），不退回全工具 agent。"""
    from ds_course_agent.rag.agent import AgentService

    service = object.__new__(AgentService)
    service.llm = None  # 缺依赖
    service.tool_registry = None
    service._agent_cache_by_tools = {}
    with pytest.raises(RuntimeError):
        service._agent_for_tools(["course_rag_tool"])


def test_t5_code_demo_fast_path_skips_concept_map(monkeypatch):
    """T5: code/demo (autonomous direct_llm) fast-path 经规则表且不触发 concept_map。"""
    service = _make_service(monkeypatch)
    calls = {"route": 0, "concept_map": 0}
    _spy_router_route(monkeypatch, calls)

    def spy_concept_map(question, top_k=3):
        calls["concept_map"] += 1
        return []

    monkeypatch.setattr("ds_course_agent.rag.agent.map_question_to_concepts", spy_concept_map)

    state = service._prepare_query_route("请用 Python 演示一次交叉验证", "session-t5c", "student-t5c")

    assert state.decision.route is RouteType.GENERIC_AGENT
    assert state.decision.direct_llm_answer is True
    assert calls["route"] == 1  # 经规则表
    assert calls["concept_map"] == 0  # demo fast-path 不跑 concept_map
    assert state.context.fast_path is True


def test_t6_every_route_type_has_a_handler(monkeypatch):
    """T6: 每个 RouteType 都被某个 handler can_handle，无路由落空。"""
    from ds_course_agent.rag.route_handlers import default_route_handlers

    service = _make_gated_service(monkeypatch)
    # SkillRouteHandler.can_handle 检查这些 skill attr
    service.code_review_skill = lambda *a, **k: "code_review"
    service.learning_path_skill = lambda *a, **k: "learning_path"
    service.misconception_skill = lambda *a, **k: "misconception"
    service.explanation_skill = lambda *a, **k: "explanation"

    handlers = default_route_handlers()
    assert any(type(h).__name__ == "GenericAgentRouteHandler" for h in handlers)  # 兜底

    for route in RouteType:
        state = _route_state(route=route, allowed_tools=[], retrieval_policy="optional")
        assert any(h.can_handle(service, state) for h in handlers), f"no handler can_handle {route}"


def test_t7_datetime_schedule_predicate_is_single_implementation():
    """T7: datetime/schedule 检测谓词全库仅 utils 一份实现，router/agent 无重复方法。"""
    import ds_course_agent.rag.query_pipeline.utils as utils
    from ds_course_agent.rag.agent import AgentService
    from ds_course_agent.rag.query_pipeline.router import QueryRouter

    assert hasattr(utils, "is_datetime_request")
    assert hasattr(utils, "is_schedule_request")
    for cls in (QueryRouter, AgentService):
        assert not hasattr(cls, "_is_datetime_request"), f"{cls.__name__} 不应有私有 datetime 谓词"
        assert not hasattr(cls, "_is_schedule_request"), f"{cls.__name__} 不应有私有 schedule 谓词"


@pytest.mark.parametrize(
    ("query", "set_signal", "expected_route", "expected_allowed_tools"),
    [
        ("现在几点？", None, RouteType.CURRENT_DATETIME, ["current_datetime_tool"]),
        ("第三周讲什么内容？", None, RouteType.COURSE_SCHEDULE, ["course_schedule_tool"]),
        (
            "现在几点？",
            lambda ctx: setattr(ctx, "special_case_response", "你好，我是课程助教。"),
            RouteType.GENERIC_AGENT,
            [],
        ),
        (
            "现在几点？",
            lambda ctx: setattr(ctx, "web_search_requested", True),
            RouteType.WEB_SEARCH,
            ["web_search_tool"],
        ),
    ],
)
def test_t7_fast_path_rule_table_results_match_expected(query, set_signal, expected_route, expected_allowed_tools):
    """T7: fast-path 经规则表得到的 RouteType + allowed_tools 与预期一致（并表回归）。"""
    context = _context(query)
    if set_signal is not None:
        set_signal(context)
    decision = get_router().route(context)
    assert decision.route is expected_route
    assert decision.allowed_tools == expected_allowed_tools
