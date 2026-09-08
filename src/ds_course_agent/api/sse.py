"""Server-sent event encoding and replay responses for chat streams."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator, Mapping
from typing import Any

from fastapi.responses import StreamingResponse

from ds_course_agent.api.stream_jobs import ActiveStreamJob

_STREAM_JOB_POLL_SECONDS = 0.01


def encode_sse(payload: Mapping[str, Any]) -> str:
    """Encode one JSON payload as a server-sent event data frame."""

    return f"data: {json.dumps(dict(payload), ensure_ascii=False)}\n\n"


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
