"""Shared turn orchestration for synchronous and streaming agent entrypoints."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Iterator
from typing import Any, Protocol

from langchain_core.messages import AIMessage, HumanMessage

from ds_course_agent.rag.query_pipeline import ExecutionMode, RouteExecutionResult, RouteState
from ds_course_agent.rag.turn_events import (
    MessageDeltaEvent,
    RetrievalEndEvent,
    RetrievalStartEvent,
    RouteSelectedEvent,
    ToolEndEvent,
    ToolStartEvent,
    TurnEndEvent,
    TurnErrorEvent,
    TurnEvent,
    TurnStartEvent,
)
from ds_course_agent.tools._shared import begin_retrieval_trace, end_retrieval_trace


class TurnAgent(Protocol):
    """Agent capabilities required by the turn orchestration boundary."""

    def _prepare_query_route(
        self,
        user_input: str,
        session_id: str,
        student_id: str | None = None,
        web_search: bool = False,
    ) -> RouteState: ...

    def _execute_route(self, route_state: RouteState, stream: bool = False) -> RouteExecutionResult: ...

    def _iter_route_response(self, route_state: RouteState) -> Iterator[str | TurnEvent]: ...

    def _yield_text_chunks(self, text: str, chunk_size: int = 24) -> Iterator[str]: ...

    def _tool_progress_label(self, tool_name: str, default: str) -> str: ...


def iter_turn_events(
    agent: TurnAgent,
    user_input: str,
    session_id: str,
    *,
    student_id: str | None = None,
    web_search: bool = False,
    stream: bool,
) -> Iterator[TurnEvent]:
    """Execute one turn and emit its complete typed lifecycle."""

    resolved_student_id = student_id or "default"
    stream_id = uuid.uuid4().hex
    yield TurnStartEvent(
        stream_id=stream_id,
        session_id=session_id,
        student_id=resolved_student_id,
    )

    try:
        route_state = (
            agent._prepare_query_route(user_input, session_id, student_id, web_search=True)
            if web_search
            else agent._prepare_query_route(user_input, session_id, student_id)
        )
    except Exception as exc:
        yield TurnErrorEvent(
            stream_id=stream_id,
            message=str(exc),
            stage="route_prepare",
        )
        raise

    route_state.stream_id = stream_id
    decision = route_state.decision
    yield RouteSelectedEvent(
        stream_id=stream_id,
        family=decision.family,
        intent=decision.intent,
        execution_mode=decision.execution_mode,
        confidence=decision.confidence,
        reasons=tuple(decision.reasons),
    )
    route_state.history.add_messages([HumanMessage(content=user_input)])

    if not stream:
        result = agent._execute_route(route_state, stream=False)
        if result.content:
            yield MessageDeltaEvent(stream_id=stream_id, delta=result.content)
        route_state.history.add_messages([AIMessage(content=result.content)])
        yield TurnEndEvent(stream_id=stream_id, result=result)
        return

    if decision.execution_mode == ExecutionMode.GROUNDED_GENERATION:
        yield RetrievalStartEvent(
            stream_id=stream_id,
            tool="course_rag_tool",
            message=agent._tool_progress_label("course_rag_tool", "正在检索课程资料..."),
        )

    parts: list[str] = []
    retrieval_end_emitted = False
    retrieval_token = begin_retrieval_trace()
    try:
        for item in agent._iter_route_response(route_state):
            if isinstance(item, RetrievalEndEvent):
                retrieval_end_emitted = True
                yield item
                continue
            if isinstance(item, (ToolStartEvent, ToolEndEvent)):
                yield item
                continue
            text = item.delta if isinstance(item, MessageDeltaEvent) else str(item or "")
            if not text:
                continue
            parts.append(text)
            yield MessageDeltaEvent(stream_id=stream_id, delta=text)
    except Exception as exc:
        yield TurnErrorEvent(
            stream_id=stream_id,
            message=str(exc),
            stage="route_execute",
            partial_content="".join(parts),
        )
        raise
    finally:
        retrieval = end_retrieval_trace(retrieval_token)

    content = "".join(parts)
    if not content.strip():
        fallback_result = agent._execute_route(route_state, stream=False)
        content = fallback_result.content
        for chunk in agent._yield_text_chunks(content):
            yield MessageDeltaEvent(stream_id=stream_id, delta=chunk)
        sources = fallback_result.sources
        used_retrieval = fallback_result.used_retrieval
        degraded = fallback_result.degraded
    else:
        sources = retrieval.sources
        used_retrieval = retrieval.used_retrieval
        degraded = False

    if used_retrieval and not retrieval_end_emitted:
        yield RetrievalEndEvent(
            stream_id=stream_id,
            sources=tuple(sources),
            used_retrieval=True,
            message=f"已找到 {len(sources)} 个来源",
            tool="web_search_tool" if decision.execution_mode == ExecutionMode.WEB_PIPELINE else "course_rag_tool",
            degraded=degraded,
        )

    result = RouteExecutionResult(
        content=content,
        family=decision.family,
        intent=decision.intent,
        execution_mode=decision.execution_mode,
        sources=list(sources),
        used_retrieval=used_retrieval,
        degraded=degraded,
    )
    route_state.history.add_messages([AIMessage(content=content)])
    yield TurnEndEvent(stream_id=stream_id, result=result)


def collect_turn_result(events: Iterable[TurnEvent]) -> RouteExecutionResult:
    """Consume a turn event stream and return its terminal execution result."""

    for event in events:
        if isinstance(event, TurnEndEvent):
            return event.result
    raise RuntimeError("Turn execution ended without TurnEndEvent")


def turn_event_payload(event: TurnEvent) -> dict[str, Any]:
    """Project one typed turn event onto the stable API stream payload."""

    if isinstance(event, TurnStartEvent):
        return {
            "type": "progress",
            "phase": "routing",
            "message": "正在分析问题类型...",
            "stream_id": event.stream_id,
            "resuming": False,
        }
    if isinstance(event, RouteSelectedEvent):
        return {
            "type": "progress",
            "phase": "context",
            "message": "正在准备上下文...",
            "stream_id": event.stream_id,
            "resuming": False,
            "family": event.family.value,
            "intent": event.intent.value,
            "execution_mode": event.execution_mode.value,
            "confidence": event.confidence,
        }
    if isinstance(event, RetrievalStartEvent):
        return {
            "type": "progress",
            "phase": event.phase,
            "message": event.message,
            "stream_id": event.stream_id,
            "tool": event.tool,
            "resuming": False,
        }
    if isinstance(event, RetrievalEndEvent):
        return {
            "type": "progress",
            "phase": event.phase,
            "message": event.message,
            "stream_id": event.stream_id,
            "tool": event.tool,
            "details": {"sources": list(event.sources)},
            "resuming": False,
        }
    if isinstance(event, (ToolStartEvent, ToolEndEvent)):
        return {
            "type": "progress",
            "phase": event.phase,
            "message": event.message,
            "stream_id": event.stream_id,
            "tool": event.tool,
            "details": event.details,
            "resuming": False,
        }
    if isinstance(event, MessageDeltaEvent):
        return {
            "type": "delta",
            "delta": event.delta,
            "stream_id": event.stream_id,
            "resuming": False,
        }
    if isinstance(event, TurnEndEvent):
        result = event.result
        return {
            "type": "done",
            "content": result.content,
            "sources": result.sources,
            "used_retrieval": result.used_retrieval,
            "degraded": result.degraded,
            "family": result.family.value,
            "intent": result.intent.value,
            "execution_mode": result.execution_mode.value,
            "stream_id": event.stream_id,
        }
    return {
        "type": "error",
        "message": event.message,
        "stage": event.stage,
        "partial_content": event.partial_content,
        "stream_id": event.stream_id,
    }


__all__ = ["TurnAgent", "collect_turn_result", "iter_turn_events", "turn_event_payload"]
