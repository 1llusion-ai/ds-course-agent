"""Shared turn orchestration for synchronous and streaming agent entrypoints."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable, Iterator
from typing import Any, Protocol

from langchain_core.messages import AIMessage, HumanMessage

from ds_course_agent.agent.events import (
    MessageDeltaEvent,
    RetrievalEndEvent,
    RetrievalStartEvent,
    RouteResultEvent,
    RouteSelectedEvent,
    ToolEndEvent,
    ToolStartEvent,
    TurnEndEvent,
    TurnErrorEvent,
    TurnEvent,
    TurnStartEvent,
    build_retrieval_end_event,
)
from ds_course_agent.agent.result_finalizer import merge_route_result_facts
from ds_course_agent.agent.route_executor import (
    RouteAgent,
    build_route_result,
    execute_route,
    iter_route_response,
)
from ds_course_agent.agent.routing import ExecutionMode, RouteExecutionResult, RouteState
from ds_course_agent.runtime.model_stream import iter_text_chunks
from ds_course_agent.tools._shared import _track_retrieval, begin_retrieval_trace, end_retrieval_trace

logger = logging.getLogger(__name__)


def _schedule_session_practice(agent: TurnAgent, state: RouteState, result: RouteExecutionResult) -> None:
    loop = getattr(agent, "learning_loop", None)
    if loop is None or result.degraded or not state.decision.enrichment.record_learning_event:
        return
    if state.decision.execution_mode is ExecutionMode.GROUNDED_GENERATION and not result.used_retrieval:
        return
    try:
        loop.schedule(state.student_id, state.session_id)
    except Exception:
        logger.exception("Failed to schedule practice after session %s", state.session_id)


class TurnAgent(RouteAgent, Protocol):
    """Agent capabilities required by the turn orchestration boundary."""

    def _prepare_query_route(
        self,
        user_input: str,
        session_id: str,
        student_id: str | None = None,
        web_search: bool = False,
    ) -> RouteState: ...

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
        result = execute_route(agent, route_state, stream=False)
        if result.content:
            yield MessageDeltaEvent(stream_id=stream_id, delta=result.content)
        route_state.history.add_messages([AIMessage(content=result.content)])
        _schedule_session_practice(agent, route_state, result)
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
    route_result: RouteExecutionResult | None = None
    degraded = False
    retrieval_token = begin_retrieval_trace()
    try:
        for item in iter_route_response(agent, route_state):
            if isinstance(item, RouteResultEvent):
                route_result = item.result
                degraded = degraded or item.result.degraded
                _track_retrieval(
                    item.result.sources,
                    attempted=item.result.retrieval_attempted,
                    used=item.result.used_retrieval,
                )
                continue
            if isinstance(item, RetrievalEndEvent):
                degraded = degraded or item.degraded
                _track_retrieval(
                    list(item.sources),
                    attempted=item.retrieval_attempted,
                    used=item.used_retrieval,
                )
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
    if route_result is not None:
        content = route_result.content
        if not "".join(parts).strip():
            for chunk in iter_text_chunks(content):
                yield MessageDeltaEvent(stream_id=stream_id, delta=chunk)
        result = merge_route_result_facts(
            route_result,
            retrieval,
            degraded=degraded,
        )
    else:
        result = build_route_result(route_state, content, retrieval=retrieval, degraded=degraded)

    if result.retrieval_attempted and not retrieval_end_emitted:
        yield build_retrieval_end_event(
            stream_id=stream_id,
            sources=tuple(result.sources),
            retrieval_attempted=result.retrieval_attempted,
            used_retrieval=result.used_retrieval,
            message=(f"已找到 {len(result.sources)} 个来源" if result.used_retrieval else "未找到可用来源"),
            tool="web_search_tool" if decision.execution_mode == ExecutionMode.WEB_PIPELINE else "course_rag_tool",
            degraded=result.degraded,
        )

    route_state.history.add_messages([AIMessage(content=result.content)])
    _schedule_session_practice(agent, route_state, result)
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
            "details": {
                "sources": list(event.sources),
                "retrieval_attempted": event.retrieval_attempted,
                "used_retrieval": event.used_retrieval,
                "degraded": event.degraded,
            },
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
            "retrieval_attempted": result.retrieval_attempted,
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
