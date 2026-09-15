"""Typed SQLite persistence for application sessions and messages."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

import ds_course_agent.shared.config as config
from ds_course_agent.shared.database import Migration, connect_sqlite

SESSION_MIGRATIONS = (
    Migration(
        version=2,
        name="create_session_message_tables",
        statements=(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                student_id TEXT NOT NULL,
                title TEXT NOT NULL,
                title_source TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                deleted_at TEXT,
                title_generation_attempts INTEGER NOT NULL DEFAULT 0,
                title_generation_pending INTEGER NOT NULL DEFAULT 0,
                title_repaired_from TEXT,
                legacy_session_id TEXT,
                UNIQUE (id, student_id)
            )
            """,
            """
            CREATE INDEX idx_sessions_student_updated
            ON sessions(student_id, deleted_at, updated_at DESC)
            """,
            """
            CREATE TABLE messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                student_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                turn_id TEXT,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                route_family TEXT,
                route_intent TEXT,
                execution_mode TEXT,
                generation_status TEXT NOT NULL DEFAULT 'completed' CHECK (
                    generation_status IN ('completed', 'stopped', 'error')
                ),
                generation_error TEXT,
                retrieval_attempted INTEGER NOT NULL DEFAULT 0,
                used_retrieval INTEGER NOT NULL DEFAULT 0,
                degraded INTEGER NOT NULL DEFAULT 0,
                web_search_requested INTEGER NOT NULL DEFAULT 0,
                web_search_used INTEGER NOT NULL DEFAULT 0,
                web_search_status TEXT NOT NULL DEFAULT 'not_requested',
                web_search_reason TEXT,
                sources_json TEXT,
                progress_json TEXT,
                progress_events_json TEXT,
                metadata_json TEXT,
                langchain_payload_json TEXT,
                UNIQUE (session_id, position),
                FOREIGN KEY (session_id, student_id)
                    REFERENCES sessions(id, student_id) ON DELETE CASCADE
            )
            """,
            """
            CREATE INDEX idx_messages_student_session_position
            ON messages(student_id, session_id, position)
            """,
            """
            CREATE TABLE deleted_session_ids (
                session_id TEXT PRIMARY KEY,
                deleted_at TEXT NOT NULL
            )
            """,
        ),
    ),
)


@dataclass(frozen=True)
class SessionRecord:
    session_id: str
    student_id: str
    title: str
    title_source: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0
    deleted_at: datetime | None = None
    title_generation_attempts: int = 0
    title_generation_pending: bool = False
    title_repaired_from: str | None = None
    legacy_session_id: str | None = None


@dataclass(frozen=True)
class MessageRecord:
    message_id: str
    session_id: str
    student_id: str
    position: int
    role: str
    content: str
    created_at: datetime
    turn_id: str | None = None
    route_family: str | None = None
    route_intent: str | None = None
    execution_mode: str | None = None
    generation_status: str = "completed"
    generation_error: str | None = None
    retrieval_attempted: bool = False
    used_retrieval: bool = False
    degraded: bool = False
    web_search_requested: bool = False
    web_search_used: bool = False
    web_search_status: str = "not_requested"
    web_search_reason: str | None = None
    sources: list[dict[str, Any]] | None = None
    progress: dict[str, Any] | None = None
    progress_events: list[dict[str, Any]] | None = None
    metadata: dict[str, Any] | None = None
    langchain_payload: dict[str, Any] | None = None


class SessionRepository(Protocol):
    def create_session(self, record: SessionRecord) -> None: ...

    def get_session(self, student_id: str, session_id: str) -> SessionRecord | None: ...

    def find_session(self, session_id: str) -> SessionRecord | None: ...

    def list_sessions(self, student_id: str) -> tuple[SessionRecord, ...]: ...

    def save_session(self, record: SessionRecord) -> None: ...

    def delete_session(self, student_id: str, session_id: str) -> bool: ...

    def append_message(self, record: MessageRecord) -> MessageRecord: ...

    def append_messages(self, records: Sequence[MessageRecord]) -> tuple[MessageRecord, ...]: ...

    def replace_message(self, record: MessageRecord) -> bool: ...

    def delete_message(self, student_id: str, session_id: str, message_id: str) -> bool: ...

    def list_messages(self, student_id: str, session_id: str) -> tuple[MessageRecord, ...]: ...

    def clear_messages(self, student_id: str, session_id: str) -> int: ...


class SQLiteSessionRepository:
    """Student-scoped session repository backed by ``var/app.db``."""

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path or config.APP_DB_PATH)

    def migrate(self) -> tuple[Migration, ...]:
        from ds_course_agent.shared.database import SQLiteMigrationRunner

        return SQLiteMigrationRunner(self._path).apply(SESSION_MIGRATIONS)

    def create_session(self, record: SessionRecord) -> None:
        self._validate_session(record)
        self.migrate()
        connection = connect_sqlite(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO sessions (
                    id, student_id, title, title_source, created_at, updated_at,
                    deleted_at, title_generation_attempts, title_generation_pending,
                    title_repaired_from, legacy_session_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._session_values(record),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def save_session(self, record: SessionRecord) -> None:
        self._validate_session(record)
        self.migrate()
        connection = connect_sqlite(self._path)
        try:
            cursor = connection.execute(
                """
                UPDATE sessions SET title = ?, title_source = ?, updated_at = ?,
                    deleted_at = ?, title_generation_attempts = ?,
                    title_generation_pending = ?, title_repaired_from = ?,
                    legacy_session_id = ?
                WHERE id = ? AND student_id = ?
                """,
                (
                    record.title,
                    record.title_source,
                    self._iso(record.updated_at),
                    self._iso(record.deleted_at) if record.deleted_at else None,
                    record.title_generation_attempts,
                    int(record.title_generation_pending),
                    record.title_repaired_from,
                    record.legacy_session_id,
                    record.session_id,
                    record.student_id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(record.session_id)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_session(self, student_id: str, session_id: str) -> SessionRecord | None:
        self._validate_identity(student_id, session_id)
        self.migrate()
        connection = connect_sqlite(self._path)
        try:
            row = connection.execute(
                self._session_select() + " WHERE s.id = ? AND s.student_id = ? AND s.deleted_at IS NULL",
                (session_id, student_id),
            ).fetchone()
        finally:
            connection.close()
        return self._session_from_row(row) if row else None

    def find_session(self, session_id: str) -> SessionRecord | None:
        if not session_id.strip():
            raise ValueError("session_id is required")
        self.migrate()
        connection = connect_sqlite(self._path)
        try:
            row = connection.execute(
                self._session_select() + " WHERE s.id = ? AND s.deleted_at IS NULL",
                (session_id,),
            ).fetchone()
        finally:
            connection.close()
        return self._session_from_row(row) if row else None

    def list_sessions(self, student_id: str) -> tuple[SessionRecord, ...]:
        self._validate_student_id(student_id)
        self.migrate()
        connection = connect_sqlite(self._path)
        try:
            rows = connection.execute(
                self._session_select()
                + " WHERE s.student_id = ? AND s.deleted_at IS NULL ORDER BY s.updated_at DESC, s.id DESC",
                (student_id,),
            ).fetchall()
        finally:
            connection.close()
        return tuple(self._session_from_row(row) for row in rows)

    def delete_session(self, student_id: str, session_id: str) -> bool:
        self._validate_identity(student_id, session_id)
        self.migrate()
        now = self._iso(datetime.now(timezone.utc))
        connection = connect_sqlite(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT 1 FROM sessions WHERE id = ? AND student_id = ? AND deleted_at IS NULL",
                (session_id, student_id),
            ).fetchone()
            if row is None:
                connection.rollback()
                return False
            connection.execute("DELETE FROM messages WHERE session_id = ? AND student_id = ?", (session_id, student_id))
            connection.execute(
                "UPDATE sessions SET deleted_at = ?, updated_at = ? WHERE id = ? AND student_id = ?",
                (now, now, session_id, student_id),
            )
            connection.execute(
                "INSERT OR REPLACE INTO deleted_session_ids (session_id, deleted_at) VALUES (?, ?)",
                (session_id, now),
            )
            connection.commit()
            return True
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def append_message(self, record: MessageRecord) -> MessageRecord:
        return self.append_messages((record,))[0]

    def append_messages(self, records: Sequence[MessageRecord]) -> tuple[MessageRecord, ...]:
        batch = tuple(records)
        if not batch:
            return ()
        for record in batch:
            self._validate_message(record, require_position=False)
        identities = {(record.student_id, record.session_id) for record in batch}
        if len(identities) != 1:
            raise ValueError("message batch must belong to one session")
        self.migrate()
        connection = connect_sqlite(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            active_session = connection.execute(
                "SELECT 1 FROM sessions WHERE id = ? AND student_id = ? AND deleted_at IS NULL",
                (batch[0].session_id, batch[0].student_id),
            ).fetchone()
            if active_session is None:
                raise KeyError(batch[0].session_id)
            next_position = int(
                connection.execute(
                    "SELECT COALESCE(MAX(position), -1) + 1 FROM messages WHERE session_id = ? AND student_id = ?",
                    (batch[0].session_id, batch[0].student_id),
                ).fetchone()[0]
            )
            stored_records = tuple(
                MessageRecord(**{**item.__dict__, "position": next_position + offset})
                for offset, item in enumerate(batch)
            )
            for stored in stored_records:
                connection.execute(self._message_insert_sql(), self._message_values(stored))
            connection.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ? AND student_id = ? AND deleted_at IS NULL",
                (
                    self._iso(stored_records[-1].created_at),
                    stored_records[-1].session_id,
                    stored_records[-1].student_id,
                ),
            )
            connection.commit()
            return stored_records
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def replace_message(self, record: MessageRecord) -> bool:
        self._validate_message(record)
        self.migrate()
        connection = connect_sqlite(self._path)
        try:
            cursor = connection.execute(
                """
                UPDATE messages SET turn_id = ?, role = ?, content = ?, created_at = ?,
                    route_family = ?, route_intent = ?, execution_mode = ?,
                    generation_status = ?, generation_error = ?, retrieval_attempted = ?,
                    used_retrieval = ?, degraded = ?, web_search_requested = ?,
                    web_search_used = ?, web_search_status = ?, web_search_reason = ?,
                    sources_json = ?, progress_json = ?, progress_events_json = ?,
                    metadata_json = ?, langchain_payload_json = ?
                WHERE id = ? AND session_id = ? AND student_id = ?
                """,
                (*self._message_values(record)[4:], record.message_id, record.session_id, record.student_id),
            )
            connection.commit()
            return cursor.rowcount == 1
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def delete_message(self, student_id: str, session_id: str, message_id: str) -> bool:
        self._validate_identity(student_id, session_id)
        if not message_id.strip():
            raise ValueError("message_id is required")
        self.migrate()
        connection = connect_sqlite(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT position FROM messages WHERE id = ? AND session_id = ? AND student_id = ?",
                (message_id, session_id, student_id),
            ).fetchone()
            if row is None:
                connection.rollback()
                return False
            position = int(row["position"])
            connection.execute("DELETE FROM messages WHERE id = ?", (message_id,))
            connection.execute(
                "UPDATE messages SET position = -position - 1 WHERE session_id = ? AND student_id = ? AND position > ?",
                (session_id, student_id, position),
            )
            connection.execute(
                "UPDATE messages SET position = -position - 2 WHERE session_id = ? AND student_id = ? AND position < 0",
                (session_id, student_id),
            )
            connection.commit()
            return True
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def list_messages(self, student_id: str, session_id: str) -> tuple[MessageRecord, ...]:
        self._validate_identity(student_id, session_id)
        self.migrate()
        connection = connect_sqlite(self._path)
        try:
            rows = connection.execute(
                "SELECT * FROM messages WHERE student_id = ? AND session_id = ? ORDER BY position",
                (student_id, session_id),
            ).fetchall()
        finally:
            connection.close()
        return tuple(self._message_from_row(row) for row in rows)

    def list_messages_by_session(self, session_id: str) -> tuple[MessageRecord, ...]:
        session = self.find_session(session_id)
        if session is None:
            return ()
        return self.list_messages(session.student_id, session_id)

    def clear_messages(self, student_id: str, session_id: str) -> int:
        self._validate_identity(student_id, session_id)
        self.migrate()
        connection = connect_sqlite(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "DELETE FROM messages WHERE student_id = ? AND session_id = ?",
                (student_id, session_id),
            )
            connection.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ? AND student_id = ?",
                (self._iso(datetime.now(timezone.utc)), session_id, student_id),
            )
            connection.commit()
            return int(cursor.rowcount)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def replace_all_messages(self, student_id: str, session_id: str, records: Sequence[MessageRecord]) -> None:
        self._validate_identity(student_id, session_id)
        batch = tuple(records)
        for record in batch:
            self._validate_message(record)
            if record.student_id != student_id or record.session_id != session_id:
                raise ValueError("message batch identity mismatch")
        self.migrate()
        connection = connect_sqlite(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM messages WHERE student_id = ? AND session_id = ?", (student_id, session_id))
            for record in batch:
                connection.execute(self._message_insert_sql(), self._message_values(record))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def import_snapshot(
        self,
        sessions: Sequence[SessionRecord],
        messages: Sequence[MessageRecord],
        deleted_session_ids: Sequence[str] = (),
    ) -> dict[str, int]:
        """Import one legacy snapshot atomically and idempotently."""

        session_batch = tuple(sessions)
        message_batch = tuple(messages)
        deleted_ids = tuple(dict.fromkeys(item for item in deleted_session_ids if item.strip()))
        for record in session_batch:
            self._validate_session(record)
        for record in message_batch:
            self._validate_message(record)
        known_sessions = {(record.session_id, record.student_id) for record in session_batch}
        if any((record.session_id, record.student_id) not in known_sessions for record in message_batch):
            raise ValueError("every imported message must have a matching imported session")

        self.migrate()
        connection = connect_sqlite(self._path)
        counts = {
            "sessions_imported": 0,
            "sessions_skipped": 0,
            "messages_imported": 0,
            "messages_skipped": 0,
            "tombstones_imported": 0,
        }
        try:
            connection.execute("BEGIN IMMEDIATE")
            now = self._iso(datetime.now(timezone.utc))
            for session_id in deleted_ids:
                cursor = connection.execute(
                    "INSERT OR IGNORE INTO deleted_session_ids (session_id, deleted_at) VALUES (?, ?)",
                    (session_id, now),
                )
                counts["tombstones_imported"] += int(cursor.rowcount == 1)

            tombstones = {
                str(row["session_id"])
                for row in connection.execute("SELECT session_id FROM deleted_session_ids").fetchall()
            }
            for record in session_batch:
                if record.session_id in tombstones:
                    counts["sessions_skipped"] += 1
                    continue
                values = self._session_values(record)
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO sessions (
                        id, student_id, title, title_source, created_at, updated_at,
                        deleted_at, title_generation_attempts, title_generation_pending,
                        title_repaired_from, legacy_session_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
                if cursor.rowcount == 1:
                    counts["sessions_imported"] += 1
                    continue
                existing = connection.execute("SELECT * FROM sessions WHERE id = ?", (record.session_id,)).fetchone()
                existing_values = tuple(
                    existing[key]
                    for key in (
                        "id",
                        "student_id",
                        "title",
                        "title_source",
                        "created_at",
                        "updated_at",
                        "deleted_at",
                        "title_generation_attempts",
                        "title_generation_pending",
                        "title_repaired_from",
                        "legacy_session_id",
                    )
                )
                if existing_values != values:
                    raise ValueError(f"session import conflict: {record.session_id}")
                counts["sessions_skipped"] += 1

            for record in message_batch:
                if record.session_id in tombstones:
                    counts["messages_skipped"] += 1
                    continue
                values = self._message_values(record)
                cursor = connection.execute(
                    self._message_insert_sql().replace("INSERT INTO", "INSERT OR IGNORE INTO", 1), values
                )
                if cursor.rowcount == 1:
                    counts["messages_imported"] += 1
                    continue
                existing = connection.execute(
                    "SELECT * FROM messages WHERE session_id = ? AND position = ?",
                    (record.session_id, record.position),
                ).fetchone()
                if existing is None:
                    raise ValueError(f"message import conflict: {record.message_id}")
                existing_values = tuple(
                    existing[key]
                    for key in (
                        "id",
                        "session_id",
                        "student_id",
                        "position",
                        "turn_id",
                        "role",
                        "content",
                        "created_at",
                        "route_family",
                        "route_intent",
                        "execution_mode",
                        "generation_status",
                        "generation_error",
                        "retrieval_attempted",
                        "used_retrieval",
                        "degraded",
                        "web_search_requested",
                        "web_search_used",
                        "web_search_status",
                        "web_search_reason",
                        "sources_json",
                        "progress_json",
                        "progress_events_json",
                        "metadata_json",
                        "langchain_payload_json",
                    )
                )
                if existing_values != values:
                    raise ValueError(f"message import conflict: {record.session_id}:{record.position}")
                counts["messages_skipped"] += 1
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return counts

    @staticmethod
    def _session_select() -> str:
        return (
            "SELECT s.*, (SELECT COUNT(*) FROM messages m "
            "WHERE m.session_id = s.id AND m.student_id = s.student_id) AS message_count "
            "FROM sessions s"
        )

    @staticmethod
    def _message_insert_sql() -> str:
        return """
            INSERT INTO messages (
                id, session_id, student_id, position, turn_id, role, content, created_at,
                route_family, route_intent, execution_mode, generation_status,
                generation_error, retrieval_attempted, used_retrieval, degraded,
                web_search_requested, web_search_used, web_search_status,
                web_search_reason, sources_json, progress_json, progress_events_json,
                metadata_json, langchain_payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

    @classmethod
    def _session_values(cls, record: SessionRecord) -> tuple[object, ...]:
        return (
            record.session_id,
            record.student_id,
            record.title,
            record.title_source,
            cls._iso(record.created_at),
            cls._iso(record.updated_at),
            cls._iso(record.deleted_at) if record.deleted_at else None,
            record.title_generation_attempts,
            int(record.title_generation_pending),
            record.title_repaired_from,
            record.legacy_session_id,
        )

    @classmethod
    def _message_values(cls, record: MessageRecord) -> tuple[object, ...]:
        return (
            record.message_id,
            record.session_id,
            record.student_id,
            record.position,
            record.turn_id,
            record.role,
            record.content,
            cls._iso(record.created_at),
            record.route_family,
            record.route_intent,
            record.execution_mode,
            record.generation_status,
            record.generation_error,
            int(record.retrieval_attempted),
            int(record.used_retrieval),
            int(record.degraded),
            int(record.web_search_requested),
            int(record.web_search_used),
            record.web_search_status,
            record.web_search_reason,
            cls._json(record.sources),
            cls._json(record.progress),
            cls._json(record.progress_events),
            cls._json(record.metadata),
            cls._json(record.langchain_payload),
        )

    @classmethod
    def _session_from_row(cls, row: sqlite3.Row) -> SessionRecord:
        return SessionRecord(
            session_id=str(row["id"]),
            student_id=str(row["student_id"]),
            title=str(row["title"]),
            title_source=str(row["title_source"]),
            created_at=cls._datetime(row["created_at"]),
            updated_at=cls._datetime(row["updated_at"]),
            message_count=int(row["message_count"]),
            deleted_at=cls._datetime(row["deleted_at"]) if row["deleted_at"] else None,
            title_generation_attempts=int(row["title_generation_attempts"]),
            title_generation_pending=bool(row["title_generation_pending"]),
            title_repaired_from=row["title_repaired_from"],
            legacy_session_id=row["legacy_session_id"],
        )

    @classmethod
    def _message_from_row(cls, row: sqlite3.Row) -> MessageRecord:
        return MessageRecord(
            message_id=str(row["id"]),
            session_id=str(row["session_id"]),
            student_id=str(row["student_id"]),
            position=int(row["position"]),
            turn_id=row["turn_id"],
            role=str(row["role"]),
            content=str(row["content"]),
            created_at=cls._datetime(row["created_at"]),
            route_family=row["route_family"],
            route_intent=row["route_intent"],
            execution_mode=row["execution_mode"],
            generation_status=str(row["generation_status"]),
            generation_error=row["generation_error"],
            retrieval_attempted=bool(row["retrieval_attempted"]),
            used_retrieval=bool(row["used_retrieval"]),
            degraded=bool(row["degraded"]),
            web_search_requested=bool(row["web_search_requested"]),
            web_search_used=bool(row["web_search_used"]),
            web_search_status=str(row["web_search_status"]),
            web_search_reason=row["web_search_reason"],
            sources=cls._load_json(row["sources_json"]),
            progress=cls._load_json(row["progress_json"]),
            progress_events=cls._load_json(row["progress_events_json"]),
            metadata=cls._load_json(row["metadata_json"]),
            langchain_payload=cls._load_json(row["langchain_payload_json"]),
        )

    @staticmethod
    def _json(value: Any) -> str | None:
        return None if value is None else json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _load_json(value: str | None) -> Any:
        return None if value is None else json.loads(value)

    @staticmethod
    def _iso(value: datetime) -> str:
        if value.tzinfo is None:
            return value.isoformat()
        return value.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _datetime(value: str) -> datetime:
        return datetime.fromisoformat(str(value))

    @classmethod
    def _validate_session(cls, record: SessionRecord) -> None:
        cls._validate_identity(record.student_id, record.session_id)
        if not record.title.strip() or not record.title_source.strip():
            raise ValueError("session title and title_source are required")

    @classmethod
    def _validate_message(cls, cls_record: MessageRecord, *, require_position: bool = True) -> None:
        cls._validate_identity(cls_record.student_id, cls_record.session_id)
        if not cls_record.message_id.strip():
            raise ValueError("message_id is required")
        if require_position and cls_record.position < 0:
            raise ValueError("message position must be non-negative")
        if cls_record.role not in {"user", "assistant", "system", "tool"}:
            raise ValueError("unsupported message role")

    @classmethod
    def _validate_identity(cls, student_id: str, session_id: str) -> None:
        cls._validate_student_id(student_id)
        if not session_id or not session_id.strip():
            raise ValueError("session_id is required")

    @staticmethod
    def _validate_student_id(student_id: str) -> None:
        if not student_id or not student_id.strip():
            raise ValueError("student_id is required")


__all__ = [
    "MessageRecord",
    "SESSION_MIGRATIONS",
    "SQLiteSessionRepository",
    "SessionRecord",
    "SessionRepository",
]
