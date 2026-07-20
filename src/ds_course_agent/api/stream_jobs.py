from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

_TERMINAL_RETENTION = timedelta(seconds=30)


@dataclass(frozen=True)
class StreamJobSnapshot:
    """Immutable snapshot used to restore an in-flight assistant message."""

    stream_id: str | None
    started_at: datetime
    message_timestamp: datetime
    content: str
    progress: dict[str, Any] | None
    progress_events: list[dict[str, Any]]
    last_event_id: int
    terminal: bool

    def to_dict(self) -> dict[str, Any]:
        """Return the API-safe representation of this snapshot."""

        return {
            "stream_id": self.stream_id,
            "started_at": self.started_at.isoformat(),
            "message_timestamp": self.message_timestamp.isoformat(),
            "content": self.content,
            "progress": self.progress,
            "progress_events": self.progress_events,
            "last_event_id": self.last_event_id,
        }


@dataclass
class ActiveStreamJob:
    """Thread-safe replay buffer for one session's active generation."""

    session_id: str
    student_id: str
    started_at: datetime
    message_timestamp: datetime
    cancel_event: threading.Event
    initial_content: str = ""
    initial_progress_events: list[dict[str, Any]] = field(default_factory=list)
    _events: list[dict[str, Any]] = field(default_factory=list, init=False, repr=False)
    _content_parts: list[str] = field(default_factory=list, init=False, repr=False)
    _progress_events: list[dict[str, Any]] = field(default_factory=list, init=False, repr=False)
    _stream_id: str | None = field(default=None, init=False, repr=False)
    _terminal: bool = field(default=False, init=False, repr=False)
    _finished_at: datetime | None = field(default=None, init=False, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.initial_content:
            self._content_parts.append(self.initial_content)
        if self.initial_progress_events:
            self._progress_events.extend(dict(item) for item in self.initial_progress_events)

    def publish(
        self,
        payload: dict[str, Any],
        *,
        snapshot_progress: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append an event and return the event with its monotonic id."""

        with self._lock:
            event = {
                **payload,
                "event_id": len(self._events) + 1,
            }
            self._events.append(event)

            stream_id = event.get("stream_id")
            if stream_id:
                self._stream_id = str(stream_id)

            event_type = event.get("type")
            if event_type == "delta" and event.get("delta"):
                self._content_parts.append(str(event["delta"]))
            elif event_type == "progress":
                progress_event = dict(snapshot_progress or event)
                progress_event.pop("type", None)
                progress_event.pop("event_id", None)
                self._progress_events.append(progress_event)
            elif event_type == "final":
                self._terminal = True
                self._finished_at = datetime.now()

            return dict(event)

    def snapshot(self) -> StreamJobSnapshot:
        """Return a consistent current view without exposing mutable internals."""

        with self._lock:
            progress_events = [dict(item) for item in self._progress_events]
            return StreamJobSnapshot(
                stream_id=self._stream_id,
                started_at=self.started_at,
                message_timestamp=self.message_timestamp,
                content="".join(self._content_parts),
                progress=progress_events[-1] if progress_events else None,
                progress_events=progress_events,
                last_event_id=len(self._events),
                terminal=self._terminal,
            )

    def events_after(self, event_id: int) -> tuple[list[dict[str, Any]], bool]:
        """Return events newer than ``event_id`` plus terminal state."""

        with self._lock:
            safe_event_id = max(0, int(event_id))
            events = [dict(item) for item in self._events[safe_event_id:]]
            return events, self._terminal

    def is_expired(self, now: datetime) -> bool:
        """Return whether a completed job has exceeded replay retention."""

        with self._lock:
            return bool(self._finished_at and now - self._finished_at >= _TERMINAL_RETENTION)


class StreamJobRegistry:
    """Own active/recent stream jobs and enforce session ownership."""

    def __init__(self) -> None:
        self._jobs: dict[str, ActiveStreamJob] = {}
        self._lock = threading.RLock()

    def register(
        self,
        *,
        session_id: str,
        student_id: str,
        cancel_event: threading.Event,
        message_timestamp: datetime,
        initial_content: str = "",
        initial_progress_events: list[dict[str, Any]] | None = None,
    ) -> ActiveStreamJob:
        """Register the only active generation for a session."""

        with self._lock:
            self._prune_expired_locked()
            job = ActiveStreamJob(
                session_id=session_id,
                student_id=student_id,
                started_at=datetime.now(),
                message_timestamp=message_timestamp,
                cancel_event=cancel_event,
                initial_content=initial_content,
                initial_progress_events=list(initial_progress_events or []),
            )
            self._jobs[session_id] = job
            return job

    def get_for_owner(
        self,
        session_id: str,
        student_id: str,
        *,
        active_only: bool = False,
    ) -> ActiveStreamJob | None:
        """Return an owned job, optionally excluding completed replay jobs."""

        with self._lock:
            self._prune_expired_locked()
            job = self._jobs.get(session_id)
            if not job or job.student_id != student_id:
                return None
            if active_only and job.snapshot().terminal:
                return None
            return job

    def discard(self, session_id: str, job: ActiveStreamJob | None = None) -> None:
        """Remove a job only when it is still the registered instance."""

        with self._lock:
            current = self._jobs.get(session_id)
            if current is None or (job is not None and current is not job):
                return
            self._jobs.pop(session_id, None)

    def clear(self) -> None:
        """Clear registry state for application teardown and isolated tests."""

        with self._lock:
            self._jobs.clear()

    def _prune_expired_locked(self) -> None:
        now = datetime.now()
        expired = [session_id for session_id, job in self._jobs.items() if job.is_expired(now)]
        for session_id in expired:
            self._jobs.pop(session_id, None)


stream_job_registry = StreamJobRegistry()


__all__ = [
    "ActiveStreamJob",
    "StreamJobRegistry",
    "StreamJobSnapshot",
    "stream_job_registry",
]
