"""Select and execute route handlers without owning turn history or routing policy."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Protocol, TypeVar

from ds_course_agent.agent.events import MessageDeltaEvent, RetrievalEndEvent, RouteResultEvent, TurnEvent
from ds_course_agent.agent.result_finalizer import (
    ResultFinalizerAgent,
    finalize_route_result,
)
from ds_course_agent.agent.routing import RouteExecutionResult, RouteState
from ds_course_agent.runtime.model_stream import iter_text_chunks
from ds_course_agent.tools._shared import (
    RetrievalTrace,
    _track_retrieval,
    begin_retrieval_trace,
    end_retrieval_trace,
)

if TYPE_CHECKING:
    from ds_course_agent.agent.handlers import RouteHandler

logger = logging.getLogger(__name__)
_T = TypeVar("_T")


def build_route_result(
    route_state: RouteState,
    content: str,
    *,
    retrieval: RetrievalTrace | None = None,
    degraded: bool = False,
) -> RouteExecutionResult:
    """Build the typed result envelope for one selected route execution."""

    decision = route_state.decision
    return RouteExecutionResult(
        content=str(content or ""),
        family=decision.family,
        intent=decision.intent,
        execution_mode=decision.execution_mode,
        sources=list(retrieval.sources) if retrieval is not None else [],
        retrieval_attempted=retrieval.retrieval_attempted if retrieval is not None else False,
        used_retrieval=retrieval.used_retrieval if retrieval is not None else False,
        degraded=degraded,
    )


def capture_retrieval(callback: Callable[[], _T]) -> tuple[_T, RetrievalTrace]:
    """Run one selected route body in an isolated retrieval scope."""

    token = begin_retrieval_trace()
    try:
        result = callback()
    finally:
        retrieval = end_retrieval_trace(token)
    return result, retrieval


def build_route_result_event(result: RouteExecutionResult) -> RouteResultEvent:
    """Wrap a finalized route result for the internal event stream."""

    return RouteResultEvent(result)


class RouteAgent(ResultFinalizerAgent, Protocol):
    """Capabilities needed to dispatch and finalize a selected route."""

    route_handlers: list[RouteHandler]


def select_route_handler(agent: RouteAgent, route_state: RouteState) -> RouteHandler:
    """Return the first matching handler in the configured registry."""

    handlers = getattr(agent, "route_handlers", None)
    if handlers is None:
        from ds_course_agent.agent.handlers import default_route_handlers

        handlers = default_route_handlers()
        agent.route_handlers = handlers
    for handler in handlers:
        if handler.can_handle(agent, route_state):
            return handler
    raise RuntimeError("No route handler available")


def observe_stream_end(agent: RouteAgent, route_state: RouteState, result: str, *, stream: bool = True) -> None:
    """Run observational stream-end hooks after direct streaming completes.

    Direct streaming intentionally yields tokens before postprocessing can
    transform the full answer.  This hook point is therefore observation-only:
    it lets hooks record trace/telemetry for the complete streamed text
    without changing already-sent chunks.
    """
    from ds_course_agent.shared.query_trace import trace_error

    try:
        agent._get_hooks().after_stream_end(route_state, result, agent=agent, stream=stream)
    except Exception as e:
        trace_error("hook.after_stream_end", e)
        logger.error("after_stream_end hook failed: %s", e, exc_info=True)


def execute_selected_route_handler(
    agent: RouteAgent,
    handler: RouteHandler,
    route_state: RouteState,
    stream: bool = False,
) -> RouteExecutionResult:
    """Execute an already-selected route handler without re-running selection."""
    from ds_course_agent.shared.query_trace import trace_error

    try:
        result = handler.execute(agent, route_state, stream=stream)

    except Exception as e:
        stage = "agent.stream_generate" if stream else "agent.generate"
        trace_error(stage, e)
        logger.error("%s failed: %s", stage, e, exc_info=stream)
        result = build_route_result(route_state, "", degraded=True)

    return finalize_route_result(agent, route_state, result, stream=stream)


def execute_route(agent: RouteAgent, route_state: RouteState, stream: bool = False) -> RouteExecutionResult:
    """Select and execute a route, preserving buffered failure finalization."""
    from ds_course_agent.shared.query_trace import trace_error

    try:
        handler = select_route_handler(agent, route_state)
    except Exception as e:
        stage = "agent.stream_generate" if stream else "agent.generate"
        trace_error(stage, e)
        logger.error("%s failed: %s", stage, e, exc_info=stream)
        failed_result = build_route_result(route_state, "", degraded=True)
        return finalize_route_result(agent, route_state, failed_result, stream=stream)

    return execute_selected_route_handler(agent, handler, route_state, stream=stream)


def iter_route_response(agent: RouteAgent, route_state: RouteState) -> Iterator[str | TurnEvent]:
    """Stream one selected handler and recover blank output in that boundary."""

    from ds_course_agent.shared.query_trace import trace_error

    try:
        handler = select_route_handler(agent, route_state)
        retrieval_token = begin_retrieval_trace()
        pending_blank_items: list[str | TurnEvent] = []
        streamed_parts: list[str] = []
        route_result_emitted = False
        degraded = False
        try:
            for item in handler.stream_execute(agent, route_state):
                if isinstance(item, RouteResultEvent):
                    route_result_emitted = True
                    degraded = degraded or item.result.degraded
                    _track_retrieval(
                        item.result.sources,
                        attempted=item.result.retrieval_attempted,
                        used=item.result.used_retrieval,
                    )
                    yield item
                    continue

                if isinstance(item, RetrievalEndEvent):
                    degraded = degraded or item.degraded
                    _track_retrieval(
                        list(item.sources),
                        attempted=item.retrieval_attempted,
                        used=item.used_retrieval,
                    )
                    yield item
                    continue

                if isinstance(item, MessageDeltaEvent):
                    text = item.delta
                elif isinstance(item, str):
                    text = item
                else:
                    yield item
                    continue

                streamed_parts.append(text)
                if text.strip():
                    yield from pending_blank_items
                    pending_blank_items.clear()
                    yield item
                else:
                    pending_blank_items.append(item)
        finally:
            retrieval = end_retrieval_trace(retrieval_token)

        if route_result_emitted or "".join(streamed_parts).strip():
            return

        recovered = finalize_route_result(
            agent,
            route_state,
            build_route_result(route_state, "", retrieval=retrieval, degraded=degraded),
            stream=True,
        )
        observe_stream_end(agent, route_state, recovered.content, stream=True)
        yield from iter_text_chunks(recovered.content)
        yield build_route_result_event(recovered)
    except Exception as exc:
        trace_error("agent.stream_generate", exc)
        logger.error("agent.stream_generate failed: %s", exc, exc_info=True)
        raise
