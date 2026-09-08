"""Agent hook and route-handler infrastructure tests."""

import pytest

from ds_course_agent.agent.events import ToolEndEvent, ToolStartEvent
from ds_course_agent.agent.hooks import HookManager, RetrievalGuardHook
from ds_course_agent.agent.route_executor import execute_route, iter_route_response
from ds_course_agent.agent.routing import (
    ExecutionMode,
    QueryContext,
    RetrievalPolicy,
    RouteDecision,
    RouteExecutionResult,
    RouteFamily,
    RouteIntent,
    RouteState,
)
from ds_course_agent.teaching.learner_state import LearnerStateSnapshot


def _route_state(
    *,
    family=RouteFamily.LEARNING,
    intent=RouteIntent.CODE_EXAMPLE,
    execution_mode=ExecutionMode.DIRECT_MODEL,
    retrieval_policy=RetrievalPolicy.OPTIONAL,
    allowed_tools=(),
    learner_state=None,
):
    context = QueryContext(
        original_query="什么是过拟合？",
        normalized_query="什么是过拟合",
        session_id="session-hooks",
        student_id="student-hooks",
        chat_history=[],
    )
    decision = RouteDecision(
        family=family,
        intent=intent,
        execution_mode=execution_mode,
        confidence=0.9,
        reasons=["unit-test"],
        retrieval_policy=retrieval_policy,
        allowed_tools=allowed_tools,
    )
    return RouteState(
        student_id="student-hooks",
        session_id="session-hooks",
        history=None,
        chat_history=[],
        learner_state=learner_state,
        special_case_response=None,
        matched_concepts=[],
        skill_candidate_keys=set(),
        context=context,
        decision=decision,
    )


def _web_route_state():
    return _route_state(
        family=RouteFamily.EXTERNAL_RESEARCH,
        intent=RouteIntent.WEB_RESEARCH,
        execution_mode=ExecutionMode.WEB_PIPELINE,
        retrieval_policy=RetrievalPolicy.DISABLED,
    )


def _execution_result(route_state, content, *, sources=None, used_retrieval=False, degraded=False):
    decision = route_state.decision
    return RouteExecutionResult(
        content=content,
        family=decision.family,
        intent=decision.intent,
        execution_mode=decision.execution_mode,
        sources=list(sources or []),
        used_retrieval=used_retrieval,
        degraded=degraded,
    )


def test_hook_manager_after_llm_transforms_result_in_order():
    class AddSuffix:
        def __init__(self, suffix):
            self.suffix = suffix

        def after_llm(self, state, result, **kwargs):
            return f"{result}{self.suffix}"

    manager = HookManager([AddSuffix("A"), AddSuffix("B")])

    assert manager.after_llm(_route_state(), "start") == "startAB"


def test_retrieval_guard_hook_forces_answer_and_records_trace(monkeypatch):
    from ds_course_agent.shared.query_trace import begin_query_trace, end_query_trace

    state = _route_state(
        intent=RouteIntent.CONCEPT_QA,
        execution_mode=ExecutionMode.TOOL_AGENT,
        retrieval_policy=RetrievalPolicy.REQUIRED,
        allowed_tools=("course_rag_tool",),
    )

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
    state = _route_state(retrieval_policy=RetrievalPolicy.OPTIONAL)

    class FakeAgent:
        def _retrieval_guard_skip_reason(self, route_state, result):
            return "retrieval_policy=optional"

        def _maybe_force_grounded_answer(self, question, chat_history=None, skip=False):
            assert skip is True
            return None

    assert RetrievalGuardHook().after_llm(state, "original", agent=FakeAgent()) == "original"


def test_retrieval_guard_hook_skips_grounded_rag_route_without_agent_callbacks():
    state = _route_state(
        intent=RouteIntent.CONCEPT_QA,
        execution_mode=ExecutionMode.GROUNDED_GENERATION,
        retrieval_policy=RetrievalPolicy.REQUIRED,
    )

    class FakeAgent:
        def _retrieval_guard_skip_reason(self, route_state, result):
            raise AssertionError("grounded RAG route should skip before guard callbacks")

        def _maybe_force_grounded_answer(self, question, chat_history=None, skip=False):
            raise AssertionError("grounded RAG route should not force a second RAG call")

    assert RetrievalGuardHook().after_llm(state, "grounded", agent=FakeAgent()) == "grounded"


def test_execute_route_dispatches_to_route_handler_without_if_ladder():
    from ds_course_agent.agent.service import AgentService

    calls = []

    class FakeHandler:
        def can_handle(self, agent, route_state):
            calls.append(("can", route_state.decision.intent.value))
            return True

        def execute(self, agent, route_state, *, stream=False):
            calls.append(("execute", stream))
            return _execution_result(
                route_state,
                "handled by route handler",
                sources=[{"reference": "handler source"}],
                used_retrieval=True,
            )

    service = AgentService.__new__(AgentService)
    service.route_handlers = [FakeHandler()]
    service.hooks = HookManager([])

    result = execute_route(
        service,
        _route_state(
            family=RouteFamily.COURSE_SERVICE,
            intent=RouteIntent.COURSE_SCHEDULE,
            execution_mode=ExecutionMode.DETERMINISTIC_TOOL,
            retrieval_policy=RetrievalPolicy.DISABLED,
        ),
        stream=True,
    )

    assert result.content == "handled by route handler"
    assert result.family is RouteFamily.COURSE_SERVICE
    assert result.intent is RouteIntent.COURSE_SCHEDULE
    assert result.execution_mode is ExecutionMode.DETERMINISTIC_TOOL
    assert result.sources == [{"reference": "handler source"}]
    assert result.used_retrieval is True
    assert calls == [("can", "course_schedule"), ("execute", True)]


def test_execute_route_does_not_force_second_retrieval_after_handler_retrieval():
    from ds_course_agent.agent.service import AgentService

    state = _route_state(
        intent=RouteIntent.CONCEPT_QA,
        execution_mode=ExecutionMode.TOOL_AGENT,
        retrieval_policy=RetrievalPolicy.REQUIRED,
        allowed_tools=("course_rag_tool",),
    )

    class RetrievedHandler:
        def can_handle(self, agent, route_state):
            return True

        def execute(self, agent, route_state, *, stream=False):
            return _execution_result(
                route_state,
                "grounded answer",
                sources=[{"reference": "《第1章》"}],
                used_retrieval=True,
            )

    service = AgentService.__new__(AgentService)
    service.route_handlers = [RetrievedHandler()]
    service.hooks = HookManager([RetrievalGuardHook()])
    service._maybe_force_grounded_answer = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("must not force a second retrieval")
    )

    result = execute_route(service, state)

    assert result.content == "grounded answer"
    assert result.sources == [{"reference": "《第1章》"}]
    assert result.used_retrieval is True


def test_stream_route_dispatches_to_route_handler_stream_contract():
    from ds_course_agent.agent.service import AgentService

    calls = []

    class FakeHandler:
        def can_handle(self, agent, route_state):
            calls.append(("can", route_state.decision.intent.value))
            return True

        def execute(self, agent, route_state, *, stream=False):
            raise AssertionError("stream dispatch should call stream_execute")

        def stream_execute(self, agent, route_state):
            calls.append(("stream_execute", route_state.decision.intent.value))
            yield "chunk-1"
            yield "chunk-2"

    service = AgentService.__new__(AgentService)
    service.route_handlers = [FakeHandler()]

    chunks = list(iter_route_response(service, _route_state()))

    assert chunks == ["chunk-1", "chunk-2"]
    assert calls == [("can", "code_example"), ("stream_execute", "code_example")]


def test_stream_route_exception_is_not_swallowed_or_persisted():
    from ds_course_agent.agent.service import AgentService

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
    state = _route_state(retrieval_policy=RetrievalPolicy.OPTIONAL)
    state.history = history

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
    from ds_course_agent.agent.handlers import BufferedRouteHandlerMixin
    from ds_course_agent.agent.service import AgentService

    calls = []

    class FakeBufferedHandler(BufferedRouteHandlerMixin):
        def can_handle(self, agent, route_state):
            calls.append(("can", route_state.decision.intent.value))
            return True

        def execute(self, agent, route_state, *, stream=False):
            calls.append(("execute", stream))
            return _execution_result(route_state, "buffered result")

    service = AgentService.__new__(AgentService)
    service.route_handlers = [FakeBufferedHandler()]
    service.hooks = HookManager([])

    chunks = list(
        iter_route_response(
            service,
            _route_state(
                family=RouteFamily.COURSE_SERVICE,
                intent=RouteIntent.COURSE_SCHEDULE,
                execution_mode=ExecutionMode.DETERMINISTIC_TOOL,
                retrieval_policy=RetrievalPolicy.DISABLED,
            ),
        )
    )

    from ds_course_agent.agent.events import RouteResultEvent

    assert "".join(chunk for chunk in chunks if isinstance(chunk, str)) == "buffered result"
    assert isinstance(chunks[-1], RouteResultEvent)
    assert chunks[-1].result.content == "buffered result"
    assert calls == [("can", "course_schedule"), ("execute", True)]


def test_web_search_route_handler_only_adapts_to_web_research_pipeline():
    from ds_course_agent.agent.handlers import WebSearchRouteHandler

    state = _web_route_state()
    calls = []

    class FakePipeline:
        def execute(self, agent, route_state, *, stream=False):
            calls.append(("execute", agent, route_state, stream))
            return _execution_result(route_state, "pipeline result")

        def stream_execute(self, agent, route_state):
            calls.append(("stream_execute", agent, route_state))
            yield "pipeline chunk"

    agent = object()
    handler = WebSearchRouteHandler(FakePipeline())

    assert handler.can_handle(agent, state) is True
    assert handler.execute(agent, state, stream=True).content == "pipeline result"
    assert list(handler.stream_execute(agent, state)) == ["pipeline chunk"]
    assert not hasattr(handler, "_fetch_plan")
    assert not hasattr(handler, "_prepare_web_answer_context")
    assert calls == [
        ("execute", agent, state, True),
        ("stream_execute", agent, state),
    ]


def test_web_search_route_handler_compacts_evidence_and_tracks_sources(monkeypatch):
    import ds_course_agent.shared.config as config
    import ds_course_agent.tools.web_search as web_search_module
    from ds_course_agent.agent.handlers import WebSearchRouteHandler
    from ds_course_agent.agent.service import AgentService
    from ds_course_agent.tools._shared import begin_retrieval_trace, end_retrieval_trace
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

    def fake_chat(user_input, chat_history=None, stream=False, turn_context=None, **kwargs):
        captured["user_input"] = user_input
        captured["turn_context"] = turn_context
        captured["stream"] = stream
        return "联网回答 [1]"

    service = AgentService.__new__(AgentService)
    service.direct_chat = fake_chat

    token = begin_retrieval_trace()
    result = WebSearchRouteHandler().execute(service, _web_route_state(), stream=False)
    trace = end_retrieval_trace(token)

    assert result.content == "联网回答 [1]"
    assert result.used_retrieval is True
    assert result.sources[0]["url"] == "https://example.com/overfitting"
    assert captured["stream"] is False
    assert "外部资料摘要" in captured["turn_context"]
    assert "Overfitting overview" in captured["turn_context"]
    assert trace.used_retrieval is True
    assert trace.sources[0]["url"] == "https://example.com/overfitting"


def test_web_search_route_rejects_obvious_non_teaching_queries_without_search(monkeypatch):
    import ds_course_agent.shared.config as config
    import ds_course_agent.tools.web_search as web_search_module
    from ds_course_agent.agent.handlers import WebSearchRouteHandler
    from ds_course_agent.agent.service import AgentService

    monkeypatch.setattr(config, "WEB_SEARCH_TEACHING_SCOPE_ENABLED", True)
    monkeypatch.setattr(
        web_search_module,
        "search_web",
        lambda question, **kwargs: (_ for _ in ()).throw(AssertionError("search_web should not be called")),
    )

    state = _web_route_state()
    state.context.original_query = "今天北京天气怎么样？"
    service = AgentService.__new__(AgentService)
    service.chat = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("chat should not be called"))

    result = WebSearchRouteHandler().execute(service, state, stream=False)

    assert "本次不进行通用联网搜索" in result.content
    assert result.degraded is False
    assert "学习" in result.content


def test_web_search_route_rejects_general_fact_queries_without_search(monkeypatch):
    import ds_course_agent.shared.config as config
    import ds_course_agent.tools.web_search as web_search_module
    from ds_course_agent.agent.handlers import WebSearchRouteHandler
    from ds_course_agent.agent.service import AgentService

    monkeypatch.setattr(config, "WEB_SEARCH_TEACHING_SCOPE_ENABLED", True)
    monkeypatch.setattr(
        web_search_module,
        "search_web",
        lambda question, **kwargs: (_ for _ in ()).throw(AssertionError("search_web should not be called")),
    )

    service = AgentService.__new__(AgentService)
    service.chat = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("chat should not be called"))

    state = _web_route_state()
    state.context.original_query = "詹姆斯多大了？"
    result = WebSearchRouteHandler().execute(service, state, stream=False)
    assert "本次不进行通用联网搜索" in result.content
    assert result.degraded is False
    assert "体育数据科学项目" in result.content

    state = _web_route_state()
    state.context.original_query = "美国总统是谁？"
    result = WebSearchRouteHandler().execute(service, state, stream=False)
    assert "本次不进行通用联网搜索" in result.content
    assert "历任总统年龄" in result.content


def test_web_search_adaptive_plan_searches_broadly_but_reads_fewer_pages(monkeypatch):
    import ds_course_agent.shared.config as config
    from ds_course_agent.research.policy import WebResearchPolicy

    monkeypatch.setattr(config, "WEB_SEARCH_TOP_K", 0)
    monkeypatch.setattr(config, "WEB_SEARCH_MIN_TOP_K", 8)
    monkeypatch.setattr(config, "WEB_SEARCH_MAX_TOP_K", 16)
    monkeypatch.setattr(config, "WEB_FETCH_ADAPTIVE_ENABLED", True)
    monkeypatch.setattr(config, "WEB_FETCH_TOP_N", 4)
    monkeypatch.setattr(config, "WEB_FETCH_MAX_ATTEMPTS", 8)
    monkeypatch.setattr(config, "WEB_FETCH_MAX_WORKERS", 4)

    policy = WebResearchPolicy()

    assert policy._search_top_k("什么是过拟合？") == 8
    assert policy._fetch_plan("什么是过拟合？")[:2] == (1, 4)
    assert policy._search_top_k("GitHub 高星 EDU LLM Agent 项目有哪些？") == 16
    assert policy._fetch_plan("GitHub 高星 EDU LLM Agent 项目有哪些？")[:2] == (2, 6)
    assert policy._search_top_k("DAPO") == 16
    assert policy._fetch_plan("DAPO")[:2] == (3, 8)


def test_web_search_scope_allows_data_science_prediction_queries(monkeypatch):
    import ds_course_agent.shared.config as config
    from ds_course_agent.research.policy import WebResearchPolicy

    monkeypatch.setattr(config, "WEB_SEARCH_TEACHING_SCOPE_ENABLED", True)

    policy = WebResearchPolicy()

    assert policy._web_search_scope_response("如何用 LSTM 预测比特币价格") is None


def test_web_fetch_top_n_zero_means_uncapped_not_disabled(monkeypatch):
    import ds_course_agent.shared.config as config
    from ds_course_agent.research.policy import WebResearchPolicy

    monkeypatch.setattr(config, "WEB_FETCH_TOP_N", 0)
    monkeypatch.setattr(config, "WEB_FETCH_ADAPTIVE_ENABLED", True)
    monkeypatch.setattr(config, "WEB_FETCH_MAX_ATTEMPTS", 10)

    policy = WebResearchPolicy()

    assert policy._fetch_plan("什么是过拟合？")[:2] == (1, 4)
    assert policy._candidate_fetch_urls(
        [
            {"url": "https://example.com/a", "title": "A"},
        ],
        "什么是过拟合？",
    )


def test_low_success_filter_keeps_explicit_video_and_scholarly_pdf_requests():
    from ds_course_agent.research.policy import WebResearchPolicy

    policy = WebResearchPolicy()

    assert (
        policy._is_low_success_fetch_target(
            "https://www.youtube.com/watch?v=abc",
            "读一下这个 YouTube 教程里的 PCA",
        )
        is False
    )
    assert policy._is_low_success_fetch_target("https://arxiv.org/pdf/2401.00001.pdf") is False
    assert policy._is_low_success_fetch_target("https://example.com/slides.pdf#page=3") is True


def test_web_search_route_handler_streams_answer_chunks_directly(monkeypatch):
    import ds_course_agent.shared.config as config
    import ds_course_agent.tools.web_search as web_search_module
    from ds_course_agent.agent.handlers import WebSearchRouteHandler
    from ds_course_agent.agent.service import AgentService
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

    def fake_chat(user_input, chat_history=None, stream=False, turn_context=None, **kwargs):
        assert stream is True
        observed["turn_context"] = turn_context
        yield "第一段"
        yield "第二段"

    service = AgentService.__new__(AgentService)
    service.direct_chat = fake_chat
    service.hooks = HookManager([])

    chunks = list(WebSearchRouteHandler().stream_execute(service, _web_route_state()))

    assert chunks == ["第一段", "第二段"]
    assert "Overfitting overview" in observed["turn_context"]


def test_web_search_route_handler_prefers_direct_chat_for_streaming(monkeypatch):
    import ds_course_agent.shared.config as config
    import ds_course_agent.tools.web_search as web_search_module
    from ds_course_agent.agent.handlers import WebSearchRouteHandler
    from ds_course_agent.agent.service import AgentService
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
    service.hooks = HookManager([])

    chunks = list(WebSearchRouteHandler().stream_execute(service, _web_route_state()))

    assert chunks == ["token-1", "token-2"]


def test_web_search_route_handler_stream_emits_detailed_progress_with_stream_id(monkeypatch):
    import ds_course_agent.shared.config as config
    import ds_course_agent.tools.web_fetch as web_fetch_module
    import ds_course_agent.tools.web_search as web_search_module
    from ds_course_agent.agent.handlers import WebSearchRouteHandler
    from ds_course_agent.agent.service import AgentService
    from ds_course_agent.tools.web_fetch import WebFetchResult
    from ds_course_agent.tools.web_search import WebSearchResponse, WebSearchResult

    monkeypatch.setattr(config, "WEB_FETCH_ENABLED", True)
    monkeypatch.setattr(config, "WEB_FETCH_TOP_N", 1)

    response = WebSearchResponse(
        query="什么是过拟合？",
        provider="tavily",
        results=[
            WebSearchResult(
                title="Overfitting overview",
                url="https://example.com/overfitting",
                snippet="Overfitting happens when a model fits noise.",
                provider="tavily",
            ),
        ],
        evidence_context="[1] 标题：Overfitting overview\nURL：https://example.com/overfitting\n摘要：...",
    )
    page = WebFetchResult(
        url="https://example.com/overfitting",
        final_url="https://example.com/overfitting",
        title="Overfitting full page",
        text="网页全文证据",
        extractor="html",
    )

    monkeypatch.setattr(web_search_module, "search_web", lambda question: response)
    monkeypatch.setattr(web_fetch_module, "fetch_web_page", lambda url: page)

    def direct_chat(user_input, chat_history=None, stream=False, turn_context=None):
        assert stream is True
        yield "answer"

    service = AgentService.__new__(AgentService)
    service.chat = lambda *args, **kwargs: "should not be used"
    service.direct_chat = direct_chat
    service.hooks = HookManager([])

    state = _web_route_state()
    state.stream_id = "stream-1"

    chunks = list(WebSearchRouteHandler().stream_execute(service, state))
    progress_events = [item for item in chunks if isinstance(item, (ToolStartEvent, ToolEndEvent))]
    text = "".join(item for item in chunks if isinstance(item, str))
    phases = [item.phase for item in progress_events]

    assert text == "answer"
    assert "web_search_start" in phases
    assert "web_search_results" in phases
    assert "web_fetch_page_done" in phases
    assert "web_answer_start" in phases
    result_event = next(item for item in progress_events if item.phase == "web_search_results")
    assert result_event.details["found_count"] == 1
    fetch_event = next(item for item in progress_events if item.phase == "web_fetch_page_done")
    assert fetch_event.details["domain"] == "example.com"


def test_web_search_route_handler_adds_deep_fetch_context_and_metadata(monkeypatch):
    import ds_course_agent.shared.config as config
    import ds_course_agent.tools.web_fetch as web_fetch_module
    import ds_course_agent.tools.web_search as web_search_module
    from ds_course_agent.agent.handlers import WebSearchRouteHandler
    from ds_course_agent.agent.service import AgentService
    from ds_course_agent.tools._shared import begin_retrieval_trace, end_retrieval_trace
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
    monkeypatch.setattr(web_fetch_module, "fetch_web_pages", lambda urls, **kwargs: [page])

    captured = {}

    def fake_chat(user_input, chat_history=None, stream=False, turn_context=None, **kwargs):
        captured["turn_context"] = turn_context
        return "联网深读回答 [1]"

    service = AgentService.__new__(AgentService)
    service.direct_chat = fake_chat

    token = begin_retrieval_trace()
    result = WebSearchRouteHandler().execute(service, _web_route_state(), stream=False)
    trace = end_retrieval_trace(token)

    assert result.content == "联网深读回答 [1]"
    assert result.used_retrieval is True
    assert "# Web Page Reading Evidence" in captured["turn_context"]
    assert "网页全文证据" in captured["turn_context"]
    assert trace.sources[0]["fetched"] is True
    assert trace.sources[0]["extractor"] == "html"
    assert trace.sources[0]["truncated"] is True


def test_web_search_fetch_type_error_is_not_retried_without_timeout_budget(monkeypatch):
    import ds_course_agent.shared.config as config
    import ds_course_agent.tools.web_fetch as web_fetch_module
    import ds_course_agent.tools.web_search as web_search_module
    from ds_course_agent.agent.handlers import WebSearchRouteHandler
    from ds_course_agent.agent.service import AgentService
    from ds_course_agent.tools.web_search import WebSearchResponse, WebSearchResult

    monkeypatch.setattr(config, "WEB_FETCH_ENABLED", True)
    response = WebSearchResponse(
        query="PCA",
        provider="test",
        results=[WebSearchResult(title="PCA", url="https://example.com/pca", snippet="summary")],
        evidence_context="[1] PCA summary",
    )
    monkeypatch.setattr(web_search_module, "search_web", lambda question: response)
    calls = []

    def broken_fetch(urls, **kwargs):
        calls.append((urls, kwargs))
        raise TypeError("internal fetch bug")

    monkeypatch.setattr(web_fetch_module, "fetch_web_pages", broken_fetch)
    service = AgentService.__new__(AgentService)
    service.direct_chat = lambda *args, **kwargs: "summary answer [1]"

    result = WebSearchRouteHandler().execute(service, _web_route_state(), stream=False)

    assert result.content == "summary answer [1]"
    assert len(calls) == 1
    assert calls[0][1]["total_timeout_seconds"] > 0


def test_web_search_deep_fetch_keeps_original_source_number(monkeypatch):
    import ds_course_agent.shared.config as config
    import ds_course_agent.tools.web_fetch as web_fetch_module
    import ds_course_agent.tools.web_search as web_search_module
    from ds_course_agent.agent.handlers import WebSearchRouteHandler
    from ds_course_agent.agent.service import AgentService
    from ds_course_agent.tools.web_fetch import WebFetchResult
    from ds_course_agent.tools.web_search import WebSearchResponse, WebSearchResult

    monkeypatch.setattr(config, "WEB_FETCH_ENABLED", True)

    response = WebSearchResponse(
        query="PPO 是什么？",
        provider="tavily",
        results=[
            WebSearchResult(
                title="First result",
                url="https://first.example/a",
                snippet="摘要 A",
                provider="tavily",
            ),
            WebSearchResult(
                title="Second result",
                url="https://second.example/b",
                snippet="摘要 B",
                provider="tavily",
            ),
        ],
        evidence_context=(
            "[1] 标题：First result\nURL：https://first.example/a\n摘要：摘要 A\n"
            "[2] 标题：Second result\nURL：https://second.example/b\n摘要：摘要 B"
        ),
    )
    page = WebFetchResult(
        url="https://second.example/b",
        final_url="https://second.example/b",
        title="Second full page",
        text="第二个搜索结果的网页正文证据。",
        extractor="html",
    )

    monkeypatch.setattr(web_search_module, "search_web", lambda question: response)
    monkeypatch.setattr(web_fetch_module, "fetch_web_pages", lambda urls, **kwargs: [page])

    captured = {}

    def fake_chat(user_input, chat_history=None, stream=False, turn_context=None, **kwargs):
        captured["turn_context"] = turn_context
        return "answer [2]"

    service = AgentService.__new__(AgentService)
    service.direct_chat = fake_chat

    result = WebSearchRouteHandler().execute(service, _web_route_state(), stream=False)

    assert result.content == "answer [2]"
    assert "[2] 网页：Second full page" in captured["turn_context"]
    assert "[1] 网页：Second full page" not in captured["turn_context"]
    assert "不要把所有句子都机械地标成 [1]" in captured["turn_context"]


def test_execute_route_hook_failure_still_reaches_empty_result_fallback(monkeypatch):
    import ds_course_agent.tools.course_rag as course_rag
    from ds_course_agent.agent.service import AgentService

    class EmptyHandler:
        def can_handle(self, agent, route_state):
            return True

        def execute(self, agent, route_state, *, stream=False):
            return _execution_result(route_state, "")

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

    result = execute_route(
        service,
        _route_state(
            intent=RouteIntent.CONCEPT_QA,
            execution_mode=ExecutionMode.TOOL_AGENT,
            retrieval_policy=RetrievalPolicy.REQUIRED,
            allowed_tools=("course_rag_tool",),
        ),
        stream=False,
    )

    assert "fallback course answer" in result.content
    assert "基础检索模式" in result.content


def test_query_postprocessor_preserves_boundary_static_response_contract():
    from ds_course_agent.agent.routing import QueryContext, RouteDecision, get_postprocessor

    context = QueryContext(
        original_query="美国总统是谁？",
        normalized_query="美国总统是谁",
        session_id="session-hooks",
        student_id="student-hooks",
        chat_history=[],
    )
    decision = RouteDecision(
        family=RouteFamily.BOUNDARY,
        intent=RouteIntent.REFUSAL,
        execution_mode=ExecutionMode.STATIC_RESPONSE,
        confidence=1.0,
        reasons=["unit-test boundary refusal"],
        retrieval_policy=RetrievalPolicy.DISABLED,
    )

    final_response = get_postprocessor().process(
        context,
        decision,
        "这个问题不属于《数据科学导论》课程学习范围。",
        chat_history=[],
    )

    assert final_response.content == "这个问题不属于《数据科学导论》课程学习范围。"
    assert final_response.family is RouteFamily.BOUNDARY
    assert final_response.intent is RouteIntent.REFUSAL
    assert final_response.execution_mode is ExecutionMode.STATIC_RESPONSE


def test_direct_stream_route_runs_stream_end_hooks_and_retrieval_guard_trace():
    from ds_course_agent.agent.handlers import GenericAgentRouteHandler
    from ds_course_agent.agent.service import AgentService
    from ds_course_agent.shared.query_trace import begin_query_trace, end_query_trace

    state = _route_state(retrieval_policy=RetrievalPolicy.OPTIONAL)
    observed = {}

    class CaptureStreamEndHook:
        def after_stream_end(self, route_state, result, **kwargs):
            observed["state"] = route_state
            observed["result"] = result
            observed["agent"] = kwargs.get("agent")
            observed["stream"] = kwargs.get("stream")

    def fake_chat(user_input, chat_history=None, stream=False, turn_context=None, **kwargs):
        assert stream is True
        yield "你"
        yield "好"

    service = AgentService.__new__(AgentService)
    # DIRECT_MODEL has no graph agent or tools and can use direct streaming.
    service.direct_chat = fake_chat
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


def test_direct_model_route_bypasses_graph_agent_and_tools_for_streaming():
    from ds_course_agent.agent.handlers import GenericAgentRouteHandler
    from ds_course_agent.agent.service import AgentService

    state = _route_state(retrieval_policy=RetrievalPolicy.OPTIONAL)
    captured = {}

    def forbidden_chat(*_args, **_kwargs):
        raise AssertionError("tool-calling agent should not run for direct LLM route")

    def fake_direct_chat(user_input, chat_history=None, stream=False, turn_context=None, **kwargs):
        assert stream is True
        captured["turn_context"] = turn_context
        yield "示例"
        yield "代码"

    service = AgentService.__new__(AgentService)
    service.chat = forbidden_chat
    service.direct_chat = fake_direct_chat
    service.hooks = HookManager([])

    chunks = list(GenericAgentRouteHandler().stream_execute(service, state))

    assert chunks == ["示例", "代码"]
    assert captured["turn_context"] == ""


def test_tool_agent_route_uses_only_explicit_non_empty_allowlist():
    from ds_course_agent.agent.handlers import GenericAgentRouteHandler

    state = _route_state(
        intent=RouteIntent.CONCEPT_QA,
        execution_mode=ExecutionMode.TOOL_AGENT,
        retrieval_policy=RetrievalPolicy.OPTIONAL,
        allowed_tools=("course_rag_tool",),
    )
    graph_agent = object()
    captured = {}

    class FakePostprocessor:
        def process(self, context, decision, result, chat_history=None):
            class Response:
                content = result

            return Response()

    class FakeAgent:
        def _route_execution_query(self, context, decision):
            return context.original_query

        model_runtime = type(
            "FakeRuntime",
            (),
            {
                "agent_for_tools": staticmethod(
                    lambda allowed_tools: captured.update(allowed_tools=allowed_tools) or graph_agent
                )
            },
        )()

        def direct_chat(self, *_args, **_kwargs):
            raise AssertionError("TOOL_AGENT must not use direct_chat")

        def chat(self, user_input, chat_history=None, stream=False, turn_context=None, graph_agent=None):
            captured["graph_agent"] = graph_agent
            return "tool answer"

    import ds_course_agent.agent.routing as query_pipeline

    original = query_pipeline.get_postprocessor
    query_pipeline.get_postprocessor = lambda: FakePostprocessor()
    try:
        result = GenericAgentRouteHandler().execute(FakeAgent(), state, stream=False)
    finally:
        query_pipeline.get_postprocessor = original

    assert result.content == "tool answer"
    assert result.used_retrieval is False
    assert captured == {
        "allowed_tools": ["course_rag_tool"],
        "graph_agent": graph_agent,
    }


@pytest.mark.parametrize(
    ("intent", "skill_attr"),
    [
        (RouteIntent.CODE_REVIEW, "code_review_skill"),
        (RouteIntent.LEARNING_PATH, "learning_path_skill"),
        (RouteIntent.MISCONCEPTION_REPAIR, "misconception_skill"),
        (RouteIntent.PERSONALIZED_EXPLANATION, "explanation_skill"),
    ],
)
def test_skill_route_handler_dispatches_by_intent(intent, skill_attr):
    from ds_course_agent.agent.handlers import SkillRouteHandler

    learner_state = (
        LearnerStateSnapshot(student_id="student-hooks")
        if intent in {RouteIntent.LEARNING_PATH, RouteIntent.PERSONALIZED_EXPLANATION}
        else None
    )
    state = _route_state(
        intent=intent,
        execution_mode=ExecutionMode.TEACHING_SKILL,
        retrieval_policy=RetrievalPolicy.OPTIONAL,
        learner_state=learner_state,
    )
    calls = []

    def skill(*args):
        calls.append(args)
        return f"{intent.value} answer"

    agent = type("FakeAgent", (), {skill_attr: staticmethod(skill)})()
    handler = SkillRouteHandler()

    assert handler.can_handle(agent, state) is True
    result = handler.execute(agent, state)
    assert result.content == f"{intent.value} answer"
    assert result.family is state.decision.family
    assert result.intent is intent
    assert calls
    if learner_state is not None:
        assert calls == [("什么是过拟合？", learner_state, [])]


@pytest.mark.parametrize("intent", [RouteIntent.LEARNING_PATH, RouteIntent.PERSONALIZED_EXPLANATION])
def test_personalized_skill_routes_require_learner_state(intent):
    from ds_course_agent.agent.handlers import SkillRouteHandler

    state = _route_state(intent=intent, execution_mode=ExecutionMode.TEACHING_SKILL)
    skill_attr = SkillRouteHandler._ROUTES[intent][0]
    agent = type("FakeAgent", (), {skill_attr: staticmethod(lambda *_args: "unexpected")})()

    with pytest.raises(RuntimeError, match=f"{intent.value} requires learner state enrichment"):
        SkillRouteHandler().execute(agent, state)


def test_agent_stream_messages_accepts_langgraph_model_node():
    from langchain_core.messages import AIMessageChunk

    from ds_course_agent.runtime.model_stream import iter_agent_stream_messages
    from ds_course_agent.shared.query_trace import begin_query_trace, end_query_trace

    class FakeLangGraphAgent:
        def stream(self, payload, stream_mode=None):
            assert payload == {"messages": ["hello"]}
            assert stream_mode == "messages"
            yield AIMessageChunk(content="模"), {"langgraph_node": "model"}
            yield AIMessageChunk(content="型"), {"langgraph_node": "model"}

    graph_agent = FakeLangGraphAgent()

    token = begin_query_trace({"entrypoint": "unit_test"})
    chunks = list(iter_agent_stream_messages(graph_agent, ["hello"]))
    trace = end_query_trace(token)

    assert chunks == ["模", "型"]
    summary = next(event for event in trace["events"] if event["stage"] == "agent.stream_messages")
    assert summary["data"]["emitted"] == 2
    assert summary["data"]["nodes"] == {"model": 2}


def test_agent_stream_messages_filters_tool_node_content():
    from langchain_core.messages import AIMessageChunk, ToolMessage

    from ds_course_agent.runtime.model_stream import iter_agent_stream_messages

    class FakeLangGraphAgent:
        def stream(self, payload, stream_mode=None):
            yield (
                ToolMessage(content="工具原始结果不应直接流给用户", tool_call_id="call-1"),
                {
                    "langgraph_node": "tools",
                },
            )
            yield AIMessageChunk(content="最终回答"), {"langgraph_node": "model"}

    graph_agent = FakeLangGraphAgent()

    assert list(iter_agent_stream_messages(graph_agent, ["hello"])) == ["最终回答"]


def test_context_governor_compaction_failure_records_trace_error(monkeypatch):
    from langchain_core.messages import HumanMessage

    import ds_course_agent.shared.context_governor as context_governor
    from ds_course_agent.runtime.context import govern_context_budget
    from ds_course_agent.shared.query_trace import begin_query_trace, end_query_trace

    messages = [HumanMessage(content="hello")]

    def boom(*args, **kwargs):
        raise RuntimeError("compaction boom")

    monkeypatch.setattr(context_governor, "compact_messages_to_budget", boom)

    token = begin_query_trace({"entrypoint": "unit_test"})
    result = govern_context_budget(messages, location="unit.pre_llm")
    trace = end_query_trace(token)

    assert result is messages
    assert any(error["stage"] == "context_governor.compaction_failed" for error in trace["errors"])
    assert any(event["stage"] == "context_governor.compaction_failed" for event in trace["events"])


def test_learner_state_context_is_natural_language_summary():
    from ds_course_agent.agent.message_context import format_learner_state_for_prompt
    from ds_course_agent.teaching.learner_state import learner_state_from_profile
    from ds_course_agent.teaching.profile_models import ConceptFocus, StudentProfile, WeakSpotCandidate

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

    summary = format_learner_state_for_prompt(learner_state_from_profile(profile))

    assert "Learner State Context" in summary
    assert "最近关注概念：决策树（第6章）x3" in summary
    assert "当前薄弱点：特征选择" in summary


def test_direct_model_route_passes_turn_context_without_graph_agent(monkeypatch):
    import ds_course_agent.agent.handlers as route_handlers_module
    from ds_course_agent.agent.handlers import GenericAgentRouteHandler

    state = _route_state(retrieval_policy=RetrievalPolicy.OPTIONAL)
    captured = {}

    class FakePostprocessor:
        def process(self, context, decision, result, chat_history=None):
            class Response:
                content = result

            return Response()

    monkeypatch.setattr(
        "ds_course_agent.agent.routing.get_postprocessor",
        lambda: FakePostprocessor(),
    )
    monkeypatch.setattr(
        route_handlers_module,
        "build_turn_system_context",
        lambda route_state: "turn profile context",
    )

    class FakeAgent:
        def _route_execution_query(self, context, decision):
            return context.original_query

        def direct_chat(self, user_input, chat_history=None, stream=False, turn_context=None):
            captured["turn_context"] = turn_context
            return "answer"

    result = GenericAgentRouteHandler().execute(FakeAgent(), state, stream=False)

    assert result.content == "answer"
    assert result.used_retrieval is False
    assert captured["turn_context"] == "turn profile context"


def test_agent_chat_compacts_over_budget_messages_before_llm(monkeypatch):
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    import ds_course_agent.shared.context_governor as context_governor
    from ds_course_agent.runtime.model_runtime import ModelRuntime
    from ds_course_agent.shared.context_governor import CONTEXT_SUMMARY_MARKER, ContextBudget
    from ds_course_agent.tools.registry import ToolRegistry

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

    runtime = ModelRuntime(llm=object(), tool_registry=ToolRegistry(), system_prompt="")
    graph_agent = FakeAgent()

    history = [
        HumanMessage(content="旧问题：" + "聚类" * 80),
        AIMessage(content="旧回答：" + "K-means 会迭代更新簇中心" * 60),
    ]
    result = runtime.chat(
        "当前问题：K-means 的步骤是什么？",
        chat_history=history,
        stream=False,
        turn_context="# Student Profile Context\n薄弱点：K-means",
        graph_agent=graph_agent,
    )

    assert result == "ok"
    messages = captured["messages"]
    assert isinstance(messages[0], SystemMessage)
    assert "Student Profile Context" in messages[0].content
    assert any(
        isinstance(message, SystemMessage) and message.additional_kwargs.get(CONTEXT_SUMMARY_MARKER)
        for message in messages
    )
    assert messages[-1].content == "当前问题：K-means 的步骤是什么？"
