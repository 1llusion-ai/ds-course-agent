"""Server-sent event encoding and replay responses for chat streams."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator, AsyncIterator, Mapping
from typing import Any

from fastapi.responses import StreamingResponse

from ds_course_agent.api.stream_jobs import ActiveStreamJob

_STREAM_JOB_POLL_SECONDS = 0.01
_SSE_SERIALIZATION_ERROR_CODE = "sse_serialization_error"
_SSE_SERIALIZATION_ERROR_MESSAGE = "事件内容无法安全序列化"
_MAX_SERIALIZATION_ERROR_PATH_LENGTH = 256

logger = logging.getLogger(__name__)


def _safe_value_kind(value: Any) -> str:
    """Return a non-sensitive JSON-shape label for a serialization issue."""

    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (list, tuple)):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unsupported"


def _bounded_path(path: str) -> str:
    """Bound diagnostic paths so malformed payloads cannot inflate an error frame."""

    if len(path) <= _MAX_SERIALIZATION_ERROR_PATH_LENGTH:
        return path
    return f"{path[: _MAX_SERIALIZATION_ERROR_PATH_LENGTH - 3]}..."


def _mapping_value_path(path: str, key: Any) -> str:
    """Build a useful path without serializing arbitrary mapping keys."""

    if isinstance(key, str) and len(key) <= 64 and key.isidentifier():
        return _bounded_path(f"{path}.{key}")
    return _bounded_path(f"{path}[key]")


def _find_serialization_issue(
    value: Any,
    *,
    path: str = "$",
    ancestors: set[int] | None = None,
) -> tuple[str, str] | None:
    """Find the first unsupported or circular value using JSON container rules."""

    if value is None or isinstance(value, (bool, int, float, str)):
        return None

    active_ancestors = ancestors if ancestors is not None else set()
    if isinstance(value, (list, tuple)):
        value_id = id(value)
        if value_id in active_ancestors:
            return _bounded_path(path), "circular_reference"
        active_ancestors.add(value_id)
        try:
            for index, item in enumerate(value):
                issue = _find_serialization_issue(
                    item,
                    path=_bounded_path(f"{path}[{index}]"),
                    ancestors=active_ancestors,
                )
                if issue is not None:
                    return issue
        finally:
            active_ancestors.remove(value_id)
        return None

    if isinstance(value, dict):
        value_id = id(value)
        if value_id in active_ancestors:
            return _bounded_path(path), "circular_reference"
        active_ancestors.add(value_id)
        try:
            for key, item in value.items():
                if key is not None and not isinstance(key, (bool, int, float, str)):
                    return _bounded_path(f"{path}[key]"), _safe_value_kind(key)
                issue = _find_serialization_issue(
                    item,
                    path=_mapping_value_path(path, key),
                    ancestors=active_ancestors,
                )
                if issue is not None:
                    return issue
        finally:
            active_ancestors.remove(value_id)
        return None

    return _bounded_path(path), _safe_value_kind(value)


def _serialization_error_frame(payload: Any) -> str:
    """Encode a fixed, non-sensitive error event for an invalid SSE payload."""

    try:
        issue = _find_serialization_issue(payload)
    except Exception:
        issue = None
    path, value_kind = issue or ("$", "unsupported")
    logger.warning(
        "SSE payload serialization failed: path=%s value_kind=%s",
        path,
        value_kind,
    )
    error_payload = {
        "type": "error",
        "code": _SSE_SERIALIZATION_ERROR_CODE,
        "message": _SSE_SERIALIZATION_ERROR_MESSAGE,
        "path": path,
        "value_kind": value_kind,
    }
    return f"data: {json.dumps(error_payload, ensure_ascii=False)}\n\n"


def encode_sse(payload: Mapping[str, Any]) -> str:
    """Encode one JSON payload as a server-sent event data frame."""

    try:
        materialized = dict(payload)
    except Exception:
        return _serialization_error_frame(payload)

    try:
        encoded = json.dumps(materialized, ensure_ascii=False)
    except Exception:
        return _serialization_error_frame(materialized)
    return f"data: {encoded}\n\n"


async def iter_stream_job_events(
    job: ActiveStreamJob,
    *,
    include_snapshot: bool,
) -> AsyncGenerator[dict[str, Any], None]:
    """Yield replayable job events independently from client connection lifetime."""

    cursor = 0
    if include_snapshot:
        snapshot = job.snapshot()
        yield {
            "type": "snapshot",
            **snapshot.to_dict(),
            "event_id": snapshot.last_event_id,
            "resuming": True,
        }
        cursor = snapshot.last_event_id
        if snapshot.terminal:
            terminal_events, _ = job.events_after(max(0, snapshot.last_event_id - 1))
            for event in terminal_events:
                if event.get("type") == "final":
                    yield event
            return

    while True:
        events, terminal = job.events_after(cursor)
        if events:
            for event in events:
                cursor = int(event.get("event_id") or cursor)
                yield event
            continue
        if terminal:
            return
        await asyncio.sleep(_STREAM_JOB_POLL_SECONDS)


def streaming_response(events: AsyncIterator[Mapping[str, Any]]) -> StreamingResponse:
    """Wrap typed event payloads in the stable chat SSE response contract."""

    async def encoded_events() -> AsyncGenerator[str, None]:
        async for event in events:
            yield encode_sse(event)

    return StreamingResponse(
        encoded_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


__all__ = ["encode_sse", "iter_stream_job_events", "streaming_response"]
