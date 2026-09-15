"""API-owned LangChain adapter for canonical session messages."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Sequence
from datetime import datetime, timezone

from langchain_core.messages import BaseMessage, message_to_dict, messages_from_dict

from ds_course_agent.api.session_repository import (
    MessageRecord,
    SessionRecord,
    SessionRepository,
    SQLiteSessionRepository,
)
from ds_course_agent.api.title_generation import DEFAULT_SESSION_TITLE
from ds_course_agent.shared.history import DEFAULT_MEMORY_POLICY, FileChatMessageHistory, MemoryPolicy

_SESSION_LOCKS: dict[str, threading.RLock] = {}
_SESSION_LOCKS_GUARD = threading.Lock()


def _session_lock(session_id: str) -> threading.RLock:
    with _SESSION_LOCKS_GUARD:
        lock = _SESSION_LOCKS.get(session_id)
        if lock is None:
            lock = threading.RLock()
            _SESSION_LOCKS[session_id] = lock
        return lock


def get_history(
    session_id: str,
    memory_policy: MemoryPolicy | None = None,
    *,
    student_id: str | None = None,
) -> SQLiteChatMessageHistory:
    return SQLiteChatMessageHistory(
        session_id=session_id,
        memory_policy=memory_policy,
        student_id=student_id,
    )


class SQLiteChatMessageHistory(FileChatMessageHistory):
    """LangChain history adapter over the canonical application message table."""

    def __init__(
        self,
        session_id: str,
        memory_policy: MemoryPolicy | None = None,
        *,
        student_id: str | None = None,
        repository: SessionRepository | None = None,
    ) -> None:
        self.storage_path = ""
        self.session_id = session_id
        self.file_path = f"sqlite:{session_id}"
        self.memory_policy = memory_policy or DEFAULT_MEMORY_POLICY
        self._lock = _session_lock(session_id)
        self._repository = repository or SQLiteSessionRepository()
        session = self._repository.find_session(session_id)
        if session is None:
            now = datetime.now(timezone.utc)
            resolved_student_id = student_id or session_id
            self._repository.create_session(
                SessionRecord(
                    session_id=session_id,
                    student_id=resolved_student_id,
                    title=DEFAULT_SESSION_TITLE,
                    title_source="implicit",
                    created_at=now,
                    updated_at=now,
                )
            )
            self.student_id = resolved_student_id
        else:
            if student_id and session.student_id != student_id:
                raise ValueError("session does not belong to the requested student")
            self.student_id = session.student_id

    @property
    def messages(self) -> list[BaseMessage]:
        with self._lock:
            records = self._repository.list_messages(self.student_id, self.session_id)
            payloads = []
            for record in records:
                if record.langchain_payload is not None:
                    payloads.append(record.langchain_payload)
                    continue
                message_type = {
                    "user": "human",
                    "assistant": "ai",
                    "system": "system",
                    "tool": "tool",
                }[record.role]
                payloads.append({"type": message_type, "data": {"content": record.content}})
            return self.compact_messages(messages_from_dict(payloads))

    def add_messages(self, messages: Sequence[BaseMessage]) -> None:
        self.warn_incoming_large_messages(messages)
        with self._lock:
            now = datetime.now(timezone.utc)
            records = []
            for message in messages:
                payload = message_to_dict(message)
                role = {
                    "human": "user",
                    "ai": "assistant",
                    "system": "system",
                    "tool": "tool",
                }.get(payload.get("type"), "assistant")
                records.append(
                    MessageRecord(
                        message_id=uuid.uuid4().hex,
                        session_id=self.session_id,
                        student_id=self.student_id,
                        position=-1,
                        role=role,
                        content=str(getattr(message, "content", "")),
                        created_at=now,
                        langchain_payload=payload,
                    )
                )
            self._repository.append_messages(records)
            self.warn_persisted_context(self.messages)

    def clear(self) -> None:
        with self._lock:
            self._repository.clear_messages(self.student_id, self.session_id)

    def delete(self) -> bool:
        with self._lock:
            return self._repository.delete_session(self.student_id, self.session_id)


__all__ = ["SQLiteChatMessageHistory", "get_history"]
