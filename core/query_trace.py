"""Per-request query trace utilities."""

from __future__ import annotations

import time
import traceback
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


@dataclass
class QueryTraceState:
    trace_id: str
    started_at: str
    start_perf: float
    meta: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)


_query_trace_ctx: ContextVar[Optional[QueryTraceState]] = ContextVar(
    "query_trace",
    default=None,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _elapsed_ms(state: QueryTraceState) -> int:
    return int((time.perf_counter() - state.start_perf) * 1000)


def begin_query_trace(meta: Optional[dict[str, Any]] = None):
    existing = _query_trace_ctx.get()
    if existing is not None:
        return None

    state = QueryTraceState(
        trace_id=uuid.uuid4().hex,
        started_at=_utc_now_iso(),
        start_perf=time.perf_counter(),
        meta=dict(meta or {}),
    )
    token = _query_trace_ctx.set(state)
    trace_step("trace.start", meta=state.meta)
    return token


def trace_step(stage: str, status: str = "ok", **data) -> None:
    state = _query_trace_ctx.get()
    if state is None:
        return

    state.events.append(
        {
            "ts": _utc_now_iso(),
            "offset_ms": _elapsed_ms(state),
            "stage": stage,
            "status": status,
            "data": data or {},
        }
    )


def trace_error(stage: str, exc: Exception | str, **data) -> None:
    state = _query_trace_ctx.get()
    if state is None:
        return

    message = str(exc)
    exc_type = type(exc).__name__ if isinstance(exc, Exception) else "Error"
    stack = traceback.format_exc()
    if stack.strip() == "NoneType: None":
        stack = ""

    error_item = {
        "ts": _utc_now_iso(),
        "offset_ms": _elapsed_ms(state),
        "stage": stage,
        "type": exc_type,
        "message": message,
        "data": data or {},
    }
    if stack:
        error_item["stack"] = stack

    state.errors.append(error_item)
    state.events.append(
        {
            "ts": error_item["ts"],
            "offset_ms": error_item["offset_ms"],
            "stage": stage,
            "status": "error",
            "data": {"type": exc_type, "message": message, **(data or {})},
        }
    )


def end_query_trace(token, status: str = "ok", **data) -> dict[str, Any]:
    state = _query_trace_ctx.get() or QueryTraceState(
        trace_id=uuid.uuid4().hex,
        started_at=_utc_now_iso(),
        start_perf=time.perf_counter(),
    )

    trace_step("trace.end", status=status, **data)
    duration_ms = _elapsed_ms(state)
    payload = {
        "trace_id": state.trace_id,
        "started_at": state.started_at,
        "ended_at": _utc_now_iso(),
        "duration_ms": duration_ms,
        "status": "error" if state.errors else status,
        "meta": state.meta,
        "events": state.events,
        "errors": state.errors,
    }

    if token is not None:
        _query_trace_ctx.reset(token)

    return payload
