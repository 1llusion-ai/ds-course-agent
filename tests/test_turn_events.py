"""Invariants for the shared typed turn executor."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from ds_course_agent.agent.events import (
    MessageDeltaEvent,
    RetrievalEndEvent,
    RouteSelectedEvent,
    TurnEndEvent,
    TurnErrorEvent,
    TurnStartEvent,
)
from ds_course_agent.agent.hooks import HookManager
from ds_course_agent.agent.routing import (
    EnrichmentPlan,
    ExecutionMode,
    QueryContext,
    RetrievalPolicy,
    RouteDecision,
    RouteExecutionResult,
    RouteFamily,
    RouteIntent,
    RouteState,
)
from ds_course_agent.agent.service import AgentService
from ds_course_agent.agent.turn_runner import iter_turn_events


class _History:
    def __init__(self) -> None:
        self.messages = []

    def add_messages(self, messages) -> None:
        self.messages.extend(messages)


def _state(history: _History) -> RouteState:
    context = QueryContext(
        original_query="解释 PCA",
        normalized_query="解释 pca",
        session_id="session-events",
        student_id="student-events",
        chat_history=[],
    )
    decision = RouteDecision(
        family=RouteFamily.LEARNING,
        intent=RouteIntent.CONCEPT_QA,
        execution_mode=ExecutionMode.DIRECT_MODEL,
        confidence=0.91,
        reasons=["unit-test"],
        retrieval_policy=RetrievalPolicy.OPTIONAL,
    )
    return RouteState(
        context=context,
        decision=decision,
        chat_history=[],
        student_id="student-events",
        session_id="session-events",
        history=history,
    )


def _result(content: str) -> RouteExecutionResult:
    return RouteExecutionResult(
        content=content,
        family=RouteFamily.LEARNING,
        intent=RouteIntent.CONCEPT_QA,
        execution_mode=ExecutionMode.DIRECT_MODEL,
    )


def test_sync_turn_emits_typed_lifecycle_and_persists_once(monkeypatch) -> None:
    history = _History()
    state = _state(history)
    service = AgentService.__new__(AgentService)
    service._prepare_query_route = lambda user_input, session_id, student_id=None: state
    monkeypatch.setattr(
        "ds_course_agent.agent.turn_runner.execute_route",
        lambda agent, route_state, stream=False: _result("同步回答"),
    )

    events = list(
        iter_turn_events(
            service,
            "解释 PCA",
            "session-events",
            student_id="student-events",
            stream=False,
        )
    )

    assert [type(event) for event in events] == [
        TurnStartEvent,
        RouteSelectedEvent,
        MessageDeltaEvent,
        TurnEndEvent,
    ]
    assert events[-1].result.content == "同步回答"
    assert [message.type for message in history.messages] == ["human", "ai"]


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("degraded", [False, True])
def test_session_practice_runs_once_after_successful_persisted_turn(monkeypatch, stream, degraded) -> None:
    history = _History()
    state = _state(history)
    state.decision = replace(state.decision, enrichment=EnrichmentPlan(record_learning_event=True))
    service = AgentService.__new__(AgentService)
    service._prepare_query_route = lambda *_args: state
    calls = []

    def schedule(student_id, session_id):
        assert [message.type for message in history.messages] == ["human", "ai"]
        calls.append((student_id, session_id))

    service.learning_loop = SimpleNamespace(schedule=schedule)
    result = replace(_result("教学回答"), degraded=degraded)
    monkeypatch.setattr("ds_course_agent.agent.turn_runner.execute_route", lambda *_args, **_kwargs: result)
    from ds_course_agent.agent.events import RouteResultEvent

    monkeypatch.setattr(
        "ds_course_agent.agent.turn_runner.iter_route_response",
        lambda *_args: iter([RouteResultEvent(result=result)]),
    )
    events = list(iter_turn_events(service, "解释 PCA", "session-events", student_id="student-events", stream=stream))
    assert isinstance(events[-1], TurnEndEvent)
    assert calls == ([] if degraded else [("student-events", "session-events")])


def test_empty_retrieval_does_not_schedule_practice(monkeypatch) -> None:
    state = _state(_History())
    state.decision = replace(
        state.decision,
        execution_mode=ExecutionMode.GROUNDED_GENERATION,
        enrichment=EnrichmentPlan(record_learning_event=True),
    )
    service = AgentService.__new__(AgentService)
    service._prepare_query_route = lambda *_args: state

    def unexpected(*_args):
        pytest.fail("a no-evidence response must not trigger a quiz")

    service.learning_loop = SimpleNamespace(schedule=unexpected)
    monkeypatch.setattr(
        "ds_course_agent.agent.turn_runner.execute_route", lambda *_args, **_kwargs: _result("没有相关材料")
    )
    events = list(iter_turn_events(service, "问题", "session-events", stream=False))
    assert isinstance(events[-1], TurnEndEvent)


def test_sync_and_stream_public_methods_consume_shared_executor(monkeypatch) -> None:
    import ds_course_agent.agent.service as agent_module

    service = AgentService.__new__(AgentService)
    calls: list[bool] = []

    def fake_iter_turn_events(agent, user_input, session_id, *, student_id=None, web_search=False, stream):
        assert agent is service
        calls.append(stream)
        yield TurnEndEvent(stream_id="stream-events", result=_result("统一回答"))

    monkeypatch.setattr(agent_module, "iter_turn_events", fake_iter_turn_events)

    sync_result = service.chat_with_history("问题", "session-events", student_id="student-events")
    stream_events = list(service.stream_chat_with_history("问题", "session-events", student_id="student-events"))

    assert sync_result.content == "统一回答"
    assert stream_events == [
        {
            "type": "done",
            "content": "统一回答",
            "sources": [],
            "retrieval_attempted": False,
            "used_retrieval": False,
            "degraded": False,
            "family": "learning",
            "intent": "concept_qa",
            "execution_mode": "direct_model",
            "stream_id": "stream-events",
        }
    ]
    assert calls == [False, True]


def test_stream_failure_emits_turn_error_and_does_not_persist_assistant() -> None:
    history = _History()
    state = _state(history)

    class _BrokenHandler:
        def can_handle(self, agent, route_state):
            return True

        def execute(self, agent, route_state, *, stream=False):
            raise AssertionError("stream path must not buffer")

        def stream_execute(self, agent, route_state):
            yield "部分回答"
            raise RuntimeError("stream failed")

    service = AgentService.__new__(AgentService)
    service.route_handlers = [_BrokenHandler()]
    service.hooks = HookManager([])
    service._prepare_query_route = lambda user_input, session_id, student_id=None: state

    events = []
    try:
        events.extend(
            iter_turn_events(
                service,
                "解释 PCA",
                "session-events",
                student_id="student-events",
                stream=True,
            )
        )
    except RuntimeError as exc:
        assert str(exc) == "stream failed"

    assert any(isinstance(event, MessageDeltaEvent) and event.delta == "部分回答" for event in events)
    assert any(isinstance(event, TurnErrorEvent) and event.partial_content == "部分回答" for event in events)
    assert [message.type for message in history.messages] == ["human"]


@pytest.mark.parametrize("stream_value", ["", " \n\t"], ids=["empty", "whitespace"])
def test_blank_stream_recovers_inside_selected_handler_once(monkeypatch, stream_value) -> None:
    """Blank streams recover without replaying route selection or execution."""

    history = _History()
    state = _state(history)
    source = {"reference": "first-pass"}
    calls = {
        "can_handle": 0,
        "stream_execute": 0,
        "execute": 0,
        "tool": 0,
        "after_llm": 0,
        "after_stream_end": 0,
        "execute_route": 0,
    }

    class CountingHandler:
        def can_handle(self, agent, route_state):
            calls["can_handle"] += 1
            return True

        def execute(self, agent, route_state, *, stream=False):
            calls["execute"] += 1
            raise AssertionError("blank stream recovery must not execute the handler again")

        def stream_execute(self, agent, route_state):
            calls["stream_execute"] += 1
            calls["tool"] += 1
            yield RetrievalEndEvent(
                stream_id=route_state.stream_id or "",
                sources=(source,),
                retrieval_attempted=True,
                used_retrieval=True,
                message="first pass",
            )
            yield stream_value

    class RecoveryHook:
        def after_llm(self, route_state, content, **kwargs):
            calls["after_llm"] += 1
            return "recovered"

        def after_stream_end(self, route_state, content, **kwargs):
            calls["after_stream_end"] += 1
            assert content == "recovered"

    service = AgentService.__new__(AgentService)
    service.route_handlers = [CountingHandler()]
    service.hooks = HookManager([RecoveryHook()])
    service._prepare_query_route = lambda user_input, session_id, student_id=None: state

    def unexpected_execute_route(*args, **kwargs):
        calls["execute_route"] += 1
        raise AssertionError("turn runner must not replay the route")

    monkeypatch.setattr("ds_course_agent.agent.turn_runner.execute_route", unexpected_execute_route)

    events = list(iter_turn_events(service, "解释 PCA", "session-events", stream=True))
    result = events[-1].result

    assert calls == {
        "can_handle": 1,
        "stream_execute": 1,
        "execute": 0,
        "tool": 1,
        "after_llm": 1,
        "after_stream_end": 1,
        "execute_route": 0,
    }
    assert result.content == "recovered"
    assert result.sources == [source]
    assert result.retrieval_attempted is True
    assert result.used_retrieval is True
    assert result.degraded is False
    assert not any(isinstance(event, MessageDeltaEvent) and not event.delta.strip() for event in events)


def test_stream_cancellation_does_not_project_a_terminal_result() -> None:
    """Closing a partial stream must release retrieval state without finalizing it."""

    from ds_course_agent.tools._shared import _track_retrieval, get_retrieval_trace

    history = _History()
    state = _state(history)

    class PartialHandler:
        def can_handle(self, agent, route_state):
            return True

        def stream_execute(self, agent, route_state):
            _track_retrieval([{"reference": "partial"}], attempted=True, used=True)
            yield "partial"
            yield "must not be consumed"

    service = AgentService.__new__(AgentService)
    service.route_handlers = [PartialHandler()]
    service.hooks = HookManager([])
    service._prepare_query_route = lambda user_input, session_id, student_id=None: state

    stream = iter_turn_events(service, "解释 PCA", "session-events", stream=True)
    emitted = [next(stream), next(stream), next(stream)]
    stream.close()

    assert any(isinstance(event, MessageDeltaEvent) and event.delta == "partial" for event in emitted)
    assert not any(isinstance(event, TurnEndEvent) for event in emitted)
    assert [message.type for message in history.messages] == ["human"]
    assert get_retrieval_trace().retrieval_attempted is False
