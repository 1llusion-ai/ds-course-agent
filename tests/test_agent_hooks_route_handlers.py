"""Agent hook and route-handler infrastructure tests."""

import pytest

from ds_course_agent.hooks import HookManager, RetrievalGuardHook
from ds_course_agent.rag.query_pipeline import QueryContext, RouteDecision, RouteType


def _route_state(*, route=RouteType.GENERIC_AGENT, retrieval_policy="required"):
    context = QueryContext(
        original_query="什么是过拟合？",
        normalized_query="什么是过拟合",
        session_id="session-hooks",
        student_id="student-hooks",
        chat_history=[],
    )
    decision = RouteDecision(
        route=route,
        confidence=0.9,
        reasons=["unit-test"],
        retrieval_policy=retrieval_policy,
    )
    return {
        "context": context,
        "decision": decision,
        "chat_history": [],
        "student_id": "student-hooks",
        "special_case_response": None,
        "matched_concepts": [],
    }


def test_hook_manager_after_llm_transforms_result_in_order():
    class AddSuffix:
        def __init__(self, suffix):
            self.suffix = suffix

        def after_llm(self, state, result, **kwargs):
            return f"{result}{self.suffix}"

    manager = HookManager([AddSuffix("A"), AddSuffix("B")])

    assert manager.after_llm(_route_state(), "start") == "startAB"


def test_retrieval_guard_hook_forces_answer_and_records_trace(monkeypatch):
    from ds_course_agent.rag.query_trace import begin_query_trace, end_query_trace

    state = _route_state()

    class FakeAgent:
        def _retrieval_guard_skip_reason(self, route_state, result):
            assert route_state is state
            assert result == "ungrounded"
            return None

        def _maybe_force_grounded_answer(self, question, chat_history=None, skip=False):
            assert question == "什么是过拟合？"
            assert skip is False
            return "grounded answer"

    token = begin_query_trace({"entrypoint": "unit_test"})
    result = RetrievalGuardHook().after_llm(state, "ungrounded", agent=FakeAgent())
    trace = end_query_trace(token)

    assert result == "grounded answer"
    assert any(event["stage"] == "retrieval_guard.force" for event in trace["events"])


def test_retrieval_guard_hook_preserves_result_when_skipped():
    state = _route_state(retrieval_policy="optional")

    class FakeAgent:
        def _retrieval_guard_skip_reason(self, route_state, result):
            return "retrieval_policy=optional"

        def _maybe_force_grounded_answer(self, question, chat_history=None, skip=False):
            assert skip is True
            return None

    assert RetrievalGuardHook().after_llm(state, "original", agent=FakeAgent()) == "original"


def test_retrieval_guard_hook_skips_grounded_rag_route_without_agent_callbacks():
    state = _route_state(route=RouteType.GROUNDED_RAG, retrieval_policy="required")

    class FakeAgent:
        def _retrieval_guard_skip_reason(self, route_state, result):
            raise AssertionError("grounded RAG route should skip before guard callbacks")

        def _maybe_force_grounded_answer(self, question, chat_history=None, skip=False):
            raise AssertionError("grounded RAG route should not force a second RAG call")

    assert RetrievalGuardHook().after_llm(state, "grounded", agent=FakeAgent()) == "grounded"


def test_execute_route_dispatches_to_route_handler_without_if_ladder():
    from ds_course_agent.rag.agent import AgentService

    calls = []

    class FakeHandler:
        def can_handle(self, agent, route_state):
            calls.append(("can", route_state["decision"].route.value))
            return True

        def execute(self, agent, route_state, *, stream=False):
            calls.append(("execute", stream))
            return "handled by route handler"

    service = AgentService.__new__(AgentService)
    service.route_handlers = [FakeHandler()]
    service.hooks = HookManager([])

    result = service._execute_route(_route_state(route=RouteType.COURSE_SCHEDULE), stream=True)

    assert result == "handled by route handler"
    assert calls == [("can", "course_schedule"), ("execute", True)]


def test_stream_route_dispatches_to_route_handler_stream_contract():
    from ds_course_agent.rag.agent import AgentService

    calls = []

    class FakeHandler:
        def can_handle(self, agent, route_state):
            calls.append(("can", route_state["decision"].route.value))
            return True

        def execute(self, agent, route_state, *, stream=False):
            raise AssertionError("stream dispatch should call stream_execute")

        def stream_execute(self, agent, route_state):
            calls.append(("stream_execute", route_state["decision"].route.value))
            yield "chunk-1"
            yield "chunk-2"

    service = AgentService.__new__(AgentService)
    service.route_handlers = [FakeHandler()]

    chunks = list(service._iter_route_response(_route_state(route=RouteType.GENERIC_AGENT)))

    assert chunks == ["chunk-1", "chunk-2"]
    assert calls == [("can", "generic_agent"), ("stream_execute", "generic_agent")]


def test_stream_route_exception_is_not_swallowed_or_persisted():
    from ds_course_agent.rag.agent import AgentService

    class FakeHistory:
        def __init__(self):
            self.messages = []

        def add_messages(self, messages):
            self.messages.extend(messages)

    class BrokenStreamingHandler:
        def can_handle(self, agent, route_state):
            return True

        def execute(self, agent, route_state, *, stream=False):
            raise AssertionError("stream path should call stream_execute")

        def stream_execute(self, agent, route_state):
            yield "partial answer"
            raise RuntimeError("upstream stream broke")

    history = FakeHistory()
    state = _route_state(route=RouteType.GENERIC_AGENT, retrieval_policy="optional")
    state["history"] = history

    service = AgentService.__new__(AgentService)
    service.route_handlers = [BrokenStreamingHandler()]
    service._prepare_query_route = lambda user_input, session_id, student_id=None: state

    events = []
    with pytest.raises(RuntimeError, match="upstream stream broke"):
        for event in service.stream_chat_with_history("问题", "session-hooks", student_id="student-hooks"):
            events.append(event)

    assert any(event.get("type") == "delta" and event.get("delta") == "partial answer" for event in events)
    assert [message.type for message in history.messages] == ["human"]


def test_buffered_stream_handler_uses_selected_handler_without_second_dispatch():
    from ds_course_agent.rag.agent import AgentService
    from ds_course_agent.rag.route_handlers import BufferedRouteHandlerMixin

    calls = []

    class FakeBufferedHandler(BufferedRouteHandlerMixin):
        def can_handle(self, agent, route_state):
            calls.append(("can", route_state["decision"].route.value))
            return True

        def execute(self, agent, route_state, *, stream=False):
            calls.append(("execute", stream))
            return "buffered result"

    service = AgentService.__new__(AgentService)
    service.route_handlers = [FakeBufferedHandler()]
    service.hooks = HookManager([])

    chunks = list(service._iter_route_response(_route_state(route=RouteType.COURSE_SCHEDULE)))

    assert "".join(chunks) == "buffered result"
    assert calls == [("can", "course_schedule"), ("execute", True)]


def test_web_search_route_handler_compacts_evidence_and_tracks_sources(monkeypatch):
    import ds_course_agent.shared.config as config
    from ds_course_agent.rag.agent import AgentService
    from ds_course_agent.rag.route_handlers import WebSearchRouteHandler
    from ds_course_agent.tools._shared import begin_retrieval_trace, end_retrieval_trace
    import ds_course_agent.tools.web_search as web_search_module
    from ds_course_agent.tools.web_search import WebSearchResponse, WebSearchResult

    monkeypatch.setattr(config, "WEB_FETCH_ENABLED", False)

    response = WebSearchResponse(
        query="什么是过拟合？",
        provider="tavily",
        results=[
            WebSearchResult(
                title="Overfitting overview",
                url="https://example.com/overfitting",
                snippet="Overfitting happens when a model fits noise.",
                provider="tavily",
            )
        ],
        evidence_context="[1] 标题：Overfitting overview\nURL：https://example.com/overfitting\n摘要：...",
    )
    monkeypatch.setattr(web_search_module, "search_web", lambda question: response)

    captured = {}

    def fake_chat(user_input, chat_history=None, stream=False, turn_context=None):
        captured["user_input"] = user_input
        captured["turn_context"] = turn_context
        captured["stream"] = stream
        return "联网回答 [1]"

    service = AgentService.__new__(AgentService)
    service.chat = fake_chat
    service._build_turn_system_context = lambda route_state: ""

    token = begin_retrieval_trace()
    result = WebSearchRouteHandler().execute(service, _route_state(route=RouteType.WEB_SEARCH), stream=False)
    trace = end_retrieval_trace(token)

    assert result == "联网回答 [1]"
    assert captured["stream"] is False
    assert "外部资料摘要" in captured["turn_context"]
    assert "Overfitting overview" in captured["turn_context"]
    assert trace.used_retrieval is True
    assert trace.sources[0]["url"] == "https://example.com/overfitting"


def test_web_search_route_handler_streams_answer_chunks_directly(monkeypatch):
    import ds_course_agent.shared.config as config
    from ds_course_agent.rag.agent import AgentService
    from ds_course_agent.rag.route_handlers import WebSearchRouteHandler
    import ds_course_agent.tools.web_search as web_search_module
    from ds_course_agent.tools.web_search import WebSearchResponse, WebSearchResult

    monkeypatch.setattr(config, "WEB_FETCH_ENABLED", False)

    response = WebSearchResponse(
        query="什么是过拟合？",
        provider="tavily",
        results=[
            WebSearchResult(
                title="Overfitting overview",
                url="https://example.com/overfitting",
                snippet="Overfitting happens when a model fits noise.",
                provider="tavily",
            )
        ],
        evidence_context="[1] 标题：Overfitting overview\nURL：https://example.com/overfitting\n摘要：...",
    )
    monkeypatch.setattr(web_search_module, "search_web", lambda question: response)

    observed = {}

    def fake_chat(user_input, chat_history=None, stream=False, turn_context=None):
        assert stream is True
        observed["turn_context"] = turn_context
        yield "第一段"
        yield "第二段"

    service = AgentService.__new__(AgentService)
    service.chat = fake_chat
    service._build_turn_system_context = lambda route_state: ""
    service.hooks = HookManager([])

    chunks = list(WebSearchRouteHandler().stream_execute(service, _route_state(route=RouteType.WEB_SEARCH)))

    assert chunks == ["第一段", "第二段"]
    assert "Overfitting overview" in observed["turn_context"]



def test_web_search_route_handler_prefers_direct_chat_for_streaming(monkeypatch):
    import ds_course_agent.shared.config as config
    from ds_course_agent.rag.agent import AgentService
    from ds_course_agent.rag.route_handlers import WebSearchRouteHandler
    import ds_course_agent.tools.web_search as web_search_module
    from ds_course_agent.tools.web_search import WebSearchResponse, WebSearchResult

    monkeypatch.setattr(config, "WEB_FETCH_ENABLED", False)

    response = WebSearchResponse(
        query="什么是过拟合？",
        provider="tavily",
        results=[
            WebSearchResult(
                title="Overfitting overview",
                url="https://example.com/overfitting",
                snippet="Overfitting happens when a model fits noise.",
                provider="tavily",
            )
        ],
        evidence_context="[1] 标题：Overfitting overview\nURL：https://example.com/overfitting\n摘要：...",
    )
    monkeypatch.setattr(web_search_module, "search_web", lambda question: response)

    def buffered_agent_chat(*args, **kwargs):
        raise AssertionError("web streaming should bypass LangGraph agent chat")

    def direct_chat(user_input, chat_history=None, stream=False, turn_context=None):
        assert stream is True
        yield "token-1"
        yield "token-2"

    service = AgentService.__new__(AgentService)
    service.chat = buffered_agent_chat
    service.direct_chat = direct_chat
    service._build_turn_system_context = lambda route_state: ""
    service.hooks = HookManager([])

    chunks = list(WebSearchRouteHandler().stream_execute(service, _route_state(route=RouteType.WEB_SEARCH)))

    assert chunks == ["token-1", "token-2"]



def test_web_search_route_handler_adds_deep_fetch_context_and_metadata(monkeypatch):
    import ds_course_agent.shared.config as config
    from ds_course_agent.rag.agent import AgentService
    from ds_course_agent.rag.route_handlers import WebSearchRouteHandler
    from ds_course_agent.tools._shared import begin_retrieval_trace, end_retrieval_trace
    import ds_course_agent.tools.web_fetch as web_fetch_module
    import ds_course_agent.tools.web_search as web_search_module
    from ds_course_agent.tools.web_fetch import WebFetchResult
    from ds_course_agent.tools.web_search import WebSearchResponse, WebSearchResult

    monkeypatch.setattr(config, "WEB_FETCH_ENABLED", True)

    response = WebSearchResponse(
        query="什么是过拟合？",
        provider="tavily",
        results=[
            WebSearchResult(
                title="Overfitting overview",
                url="https://example.com/overfitting",
                snippet="Overfitting happens when a model fits noise.",
                provider="tavily",
            )
        ],
        evidence_context="[1] 标题：Overfitting overview\nURL：https://example.com/overfitting\n摘要：...",
    )
    page = WebFetchResult(
        url="https://example.com/overfitting",
        final_url="https://example.com/overfitting",
        title="Overfitting full page",
        text="网页全文证据：训练集表现很好但泛化误差变差。",
        extractor="html",
        truncated=True,
    )

    monkeypatch.setattr(web_search_module, "search_web", lambda question: response)
    monkeypatch.setattr(web_fetch_module, "fetch_web_pages", lambda urls: [page])

    captured = {}

    def fake_chat(user_input, chat_history=None, stream=False, turn_context=None):
        captured["turn_context"] = turn_context
        return "联网深读回答 [1]"

    service = AgentService.__new__(AgentService)
    service.chat = fake_chat
    service._build_turn_system_context = lambda route_state: ""

    token = begin_retrieval_trace()
    result = WebSearchRouteHandler().execute(service, _route_state(route=RouteType.WEB_SEARCH), stream=False)
    trace = end_retrieval_trace(token)

    assert result == "联网深读回答 [1]"
    assert "# Web Page Reading Evidence" in captured["turn_context"]
    assert "网页全文证据" in captured["turn_context"]
    assert trace.sources[0]["fetched"] is True
    assert trace.sources[0]["extractor"] == "html"
    assert trace.sources[0]["truncated"] is True


def test_execute_route_hook_failure_still_reaches_empty_result_fallback(monkeypatch):
    from ds_course_agent.rag.agent import AgentService
    import ds_course_agent.tools.course_rag as course_rag

    class EmptyHandler:
        def can_handle(self, agent, route_state):
            return True

        def execute(self, agent, route_state, *, stream=False):
            return ""

    class BrokenAfterLlmHook:
        def after_llm(self, state, result, **kwargs):
            raise KeyError("missing key")

    class FakeCourseRagTool:
        def invoke(self, query):
            return "fallback course answer"

    monkeypatch.setattr(course_rag, "course_rag_tool", FakeCourseRagTool())

    service = AgentService.__new__(AgentService)
    service.route_handlers = [EmptyHandler()]
    service.hooks = HookManager([BrokenAfterLlmHook()])

    result = service._execute_route(_route_state(route=RouteType.GENERIC_AGENT), stream=False)

    assert "fallback course answer" in result
    assert "基础检索模式" in result


def test_direct_stream_route_runs_stream_end_hooks_and_retrieval_guard_trace():
    from ds_course_agent.rag.agent import AgentService
    from ds_course_agent.rag.query_trace import begin_query_trace, end_query_trace
    from ds_course_agent.rag.route_handlers import GenericAgentRouteHandler

    state = _route_state(route=RouteType.GENERIC_AGENT, retrieval_policy="optional")
    observed = {}

    class CaptureStreamEndHook:
        def after_stream_end(self, route_state, result, **kwargs):
            observed["state"] = route_state
            observed["result"] = result
            observed["agent"] = kwargs.get("agent")
            observed["stream"] = kwargs.get("stream")

    def fake_chat(user_input, chat_history=None, stream=False, turn_context=None):
        assert stream is True
        yield "你"
        yield "好"

    service = AgentService.__new__(AgentService)
    service.chat = fake_chat
    service.hooks = HookManager([RetrievalGuardHook(), CaptureStreamEndHook()])

    token = begin_query_trace({"entrypoint": "unit_test"})
    chunks = list(GenericAgentRouteHandler().stream_execute(service, state))
    trace = end_query_trace(token)

    assert chunks == ["你", "好"]
    assert observed == {
        "state": state,
        "result": "你好",
        "agent": service,
        "stream": True,
    }
    assert any(
        event["stage"] == "retrieval_guard.skip"
        and event["data"]["reason"] == "direct_stream:retrieval_policy=optional"
        for event in trace["events"]
    )


def test_context_governor_compaction_failure_records_trace_error(monkeypatch):
    from langchain_core.messages import HumanMessage

    import ds_course_agent.shared.context_governor as context_governor
    from ds_course_agent.rag.agent import AgentService
    from ds_course_agent.rag.query_trace import begin_query_trace, end_query_trace

    messages = [HumanMessage(content="hello")]

    def boom(*args, **kwargs):
        raise RuntimeError("compaction boom")

    monkeypatch.setattr(context_governor, "compact_messages_to_budget", boom)

    service = AgentService.__new__(AgentService)
    token = begin_query_trace({"entrypoint": "unit_test"})
    result = service._govern_context_budget(messages, location="unit.pre_llm")
    trace = end_query_trace(token)

    assert result is messages
    assert any(error["stage"] == "context_governor.compaction_failed" for error in trace["errors"])
    assert any(event["stage"] == "context_governor.compaction_failed" for event in trace["events"])


def test_student_profile_context_is_natural_language_summary():
    from ds_course_agent.rag.agent import AgentService
    from ds_course_agent.rag.profile_models import ConceptFocus, StudentProfile, WeakSpotCandidate

    service = AgentService.__new__(AgentService)
    profile = StudentProfile(student_id="student-hooks")
    profile.recent_concepts["decision_tree"] = ConceptFocus(
        concept_id="decision_tree",
        display_name="决策树",
        chapter="第6章",
        mention_count=3,
        last_mentioned_at=2.0,
    )
    profile.weak_spot_candidates.append(
        WeakSpotCandidate(
            concept_id="feature_selection",
            display_name="特征选择",
            confidence=0.8,
        )
    )

    summary = service._format_student_profile_for_prompt(profile)

    assert "Student Profile Context" in summary
    assert "最近关注概念：决策树（第6章）x3" in summary
    assert "当前薄弱点：特征选择" in summary


def test_generic_route_passes_turn_context_to_chat(monkeypatch):
    from ds_course_agent.rag.route_handlers import GenericAgentRouteHandler

    state = _route_state(route=RouteType.GENERIC_AGENT, retrieval_policy="optional")
    captured = {}

    class FakePostprocessor:
        def process(self, context, decision, result, chat_history=None):
            class Response:
                content = result

            return Response()

    monkeypatch.setattr(
        "ds_course_agent.rag.query_pipeline.get_postprocessor",
        lambda: FakePostprocessor(),
    )

    class FakeAgent:
        def _route_execution_query(self, context, decision):
            return context.original_query

        def _build_turn_system_context(self, route_state):
            assert route_state is state
            return "turn profile context"

        def chat(self, user_input, chat_history=None, stream=False, turn_context=None):
            captured["turn_context"] = turn_context
            return "answer"

    result = GenericAgentRouteHandler().execute(FakeAgent(), state, stream=False)

    assert result == "answer"
    assert captured["turn_context"] == "turn profile context"


def test_agent_chat_compacts_over_budget_messages_before_llm(monkeypatch):
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    import ds_course_agent.shared.context_governor as context_governor
    from ds_course_agent.rag.agent import AgentService
    from ds_course_agent.shared.context_governor import CONTEXT_SUMMARY_MARKER, ContextBudget

    monkeypatch.setattr(
        context_governor,
        "DEFAULT_CONTEXT_BUDGET",
        ContextBudget(context_window_tokens=80, budget_ratio=0.5),
    )

    captured = {}

    class FakeAgent:
        def invoke(self, payload):
            captured["messages"] = payload["messages"]
            return {"messages": [AIMessage(content="ok")]}

    service = AgentService.__new__(AgentService)
    service.agent = FakeAgent()

    history = [
        HumanMessage(content="旧问题：" + "聚类" * 80),
        AIMessage(content="旧回答：" + "K-means 会迭代更新簇中心" * 60),
    ]
    result = service.chat(
        "当前问题：K-means 的步骤是什么？",
        chat_history=history,
        stream=False,
        turn_context="# Student Profile Context\n薄弱点：K-means",
    )

    assert result == "ok"
    messages = captured["messages"]
    assert isinstance(messages[0], SystemMessage)
    assert "Student Profile Context" in messages[0].content
    assert any(
        isinstance(message, SystemMessage)
        and message.additional_kwargs.get(CONTEXT_SUMMARY_MARKER)
        for message in messages
    )
    assert messages[-1].content == "当前问题：K-means 的步骤是什么？"
