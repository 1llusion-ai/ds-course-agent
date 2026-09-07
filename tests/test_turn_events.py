"""Invariants for the shared typed turn executor."""

from __future__ import annotations

from ds_course_agent.hooks import HookManager
from ds_course_agent.rag.agent import AgentService
from ds_course_agent.rag.query_pipeline import (
    ExecutionMode,
    QueryContext,
    RetrievalPolicy,
    RouteDecision,
    RouteExecutionResult,
    RouteFamily,
    RouteIntent,
    RouteState,
)
from ds_course_agent.rag.turn_events import (
    MessageDeltaEvent,
    RouteSelectedEvent,
    TurnEndEvent,
    TurnErrorEvent,
    TurnStartEvent,
)


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


def test_sync_turn_emits_typed_lifecycle_and_persists_once() -> None:
    history = _History()
    state = _state(history)
    service = AgentService.__new__(AgentService)
    service._prepare_query_route = lambda user_input, session_id, student_id=None: state
    service._execute_route = lambda route_state, stream=False: _result("同步回答")

    events = list(
        service.iter_turn_events(
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


def test_sync_and_stream_public_methods_consume_shared_executor() -> None:
    service = AgentService.__new__(AgentService)
    calls: list[bool] = []

    def iter_events(user_input, session_id, *, student_id=None, web_search=False, stream):
        calls.append(stream)
        yield TurnEndEvent(stream_id="stream-events", result=_result("统一回答"))

    service.iter_turn_events = iter_events

    sync_result = service.chat_with_history("问题", "session-events", student_id="student-events")
    stream_events = list(service.stream_chat_with_history("问题", "session-events", student_id="student-events"))

    assert sync_result.content == "统一回答"
    assert stream_events == [
        {
            "type": "done",
            "content": "统一回答",
            "sources": [],
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
            service.iter_turn_events(
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
