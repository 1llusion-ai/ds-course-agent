"""Typed lifecycle events emitted by one agent turn."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, TypeAlias

from ds_course_agent.agent.routing import ExecutionMode, RouteExecutionResult, RouteFamily, RouteIntent


@dataclass(frozen=True)
class TurnStartEvent:
    """Signal that one user turn has started."""

    stream_id: str
    session_id: str
    student_id: str


@dataclass(frozen=True)
class RouteSelectedEvent:
    """Expose the immutable routing decision for the turn."""

    stream_id: str
    family: RouteFamily
    intent: RouteIntent
    execution_mode: ExecutionMode
    confidence: float
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class RetrievalStartEvent:
    """Signal the start of grounded retrieval."""

    stream_id: str
    tool: str
    message: str
    phase: str = "retrieval"


@dataclass(frozen=True)
class RetrievalEndEvent:
    """Report the retrieval facts produced during the turn."""

    stream_id: str
    sources: tuple[dict[str, Any], ...]
    retrieval_attempted: bool
    used_retrieval: bool
    message: str
    tool: str = "course_rag_tool"
    phase: str = "retrieval_sources"
    degraded: bool = False


@dataclass(frozen=True)
class MessageDeltaEvent:
    """Carry one assistant text delta."""

    stream_id: str
    delta: str


@dataclass(frozen=True)
class ToolStartEvent:
    """Signal the start of a deterministic tool stage."""

    stream_id: str
    tool: str
    phase: str
    message: str
    details: dict[str, Any] | None = None


@dataclass(frozen=True)
class ToolEndEvent:
    """Report completion or failure of a deterministic tool stage."""

    stream_id: str
    tool: str
    phase: str
    message: str
    details: dict[str, Any] | None = None
    failed: bool = False


@dataclass(frozen=True)
class RouteResultEvent:
    """Internal handler result consumed by the runner, never sent as a wire event."""

    result: RouteExecutionResult


@dataclass(frozen=True)
class TurnEndEvent:
    """Carry the complete typed result for a successful turn."""

    stream_id: str
    result: RouteExecutionResult


@dataclass(frozen=True)
class TurnErrorEvent:
    """Report a terminal turn failure before the exception is propagated."""

    stream_id: str
    message: str
    stage: str
    partial_content: str = ""


def build_retrieval_end_event(
    *,
    stream_id: str,
    sources: Iterable[dict[str, Any]],
    retrieval_attempted: bool,
    used_retrieval: bool,
    message: str,
    tool: str = "course_rag_tool",
    phase: str = "retrieval_sources",
    degraded: bool = False,
) -> RetrievalEndEvent:
    """Build the typed retrieval-completion event at the event boundary."""

    return RetrievalEndEvent(
        stream_id=stream_id,
        sources=tuple(sources),
        retrieval_attempted=retrieval_attempted,
        used_retrieval=used_retrieval,
        message=message,
        tool=tool,
        phase=phase,
        degraded=degraded,
    )


TurnEvent: TypeAlias = (
    TurnStartEvent
    | RouteSelectedEvent
    | RetrievalStartEvent
    | RetrievalEndEvent
    | MessageDeltaEvent
    | ToolStartEvent
    | ToolEndEvent
    | RouteResultEvent
    | TurnEndEvent
    | TurnErrorEvent
)


__all__ = [
    "RouteResultEvent",
    "MessageDeltaEvent",
    "RetrievalEndEvent",
    "RetrievalStartEvent",
    "RouteSelectedEvent",
    "ToolEndEvent",
    "ToolStartEvent",
    "TurnEndEvent",
    "TurnErrorEvent",
    "TurnEvent",
    "TurnStartEvent",
    "build_retrieval_end_event",
]
