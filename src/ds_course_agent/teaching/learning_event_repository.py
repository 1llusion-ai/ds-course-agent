"""Student-scoped repository for durable learning event facts."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

import ds_course_agent.shared.config as config
from ds_course_agent.shared.database import connect_sqlite
from ds_course_agent.teaching.database import migrate_learner_memory_database
from ds_course_agent.teaching.learning_events import BaseEvent, EventType


@dataclass(frozen=True)
class LearningEventRecord:
    """Persisted event plus turn and schema identity."""

    event: BaseEvent
    turn_id: str
    schema_version: int = 1


class LearningEventRepository(Protocol):
    """Persistence contract for append-only, student-scoped learning facts."""

    def append(self, record: LearningEventRecord) -> bool: ...

    def append_many(self, records: Sequence[LearningEventRecord]) -> int: ...

    def list_for_student(
        self,
        student_id: str,
        *,
        event_types: Sequence[EventType] = (),
        concept_ids: Sequence[str] = (),
        limit: int = 100,
    ) -> tuple[LearningEventRecord, ...]: ...

    def list_for_turn(self, student_id: str, session_id: str, turn_id: str) -> tuple[LearningEventRecord, ...]: ...

    def list_all_for_student(self, student_id: str) -> tuple[LearningEventRecord, ...]: ...


class SQLiteLearningEventRepository:
    """SQLite implementation backed by the teaching-owned application schema."""

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path or config.APP_DB_PATH)

    def append(self, record: LearningEventRecord) -> bool:
        """Append one event, returning false for an identical retry."""

        return self.append_many((record,)) == 1

    def append_many(self, records: Sequence[LearningEventRecord]) -> int:
        """Append one student's event batch atomically and idempotently."""

        batch = tuple(records)
        if not batch:
            return 0
        self._validate_batch(batch)
        migrate_learner_memory_database(self._path)
        connection = connect_sqlite(self._path)
        inserted = 0
        try:
            connection.execute("BEGIN IMMEDIATE")
            for record in batch:
                inserted += self._append_one(connection, record)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return inserted

    def list_for_student(
        self,
        student_id: str,
        *,
        event_types: Sequence[EventType] = (),
        concept_ids: Sequence[str] = (),
        limit: int = 100,
    ) -> tuple[LearningEventRecord, ...]:
        """Return one student's newest events with optional typed filters."""

        self._validate_student_id(student_id)
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        migrate_learner_memory_database(self._path)

        clauses = ["student_id = ?"]
        params: list[object] = [student_id]
        if event_types:
            placeholders = ", ".join("?" for _ in event_types)
            clauses.append(f"event_type IN ({placeholders})")
            params.extend(event_type.value for event_type in event_types)
        if concept_ids:
            placeholders = ", ".join("?" for _ in concept_ids)
            clauses.append(f"concept_id IN ({placeholders})")
            params.extend(concept_ids)
        params.append(limit)
        query = (
            "SELECT id, student_id, session_id, turn_id, event_type, "
            "observed_at, payload_json, schema_version FROM learning_events WHERE "
            + " AND ".join(clauses)
            + " ORDER BY observed_at DESC, rowid DESC LIMIT ?"
        )
        connection = connect_sqlite(self._path)
        try:
            rows = connection.execute(query, params).fetchall()
        finally:
            connection.close()
        return tuple(self._record_from_row(row) for row in rows)

    def list_for_turn(self, student_id: str, session_id: str, turn_id: str) -> tuple[LearningEventRecord, ...]:
        """Return all facts already written for one completed turn."""
        self._validate_student_id(student_id)
        if not session_id.strip() or not turn_id.strip():
            raise ValueError("session_id and turn_id are required")
        migrate_learner_memory_database(self._path)
        connection = connect_sqlite(self._path)
        try:
            rows = connection.execute(
                """
                SELECT id, student_id, session_id, turn_id, event_type,
                       observed_at, payload_json, schema_version
                FROM learning_events
                WHERE student_id = ? AND session_id = ? AND turn_id = ?
                ORDER BY observed_at ASC, rowid ASC
                """,
                (student_id, session_id, turn_id),
            ).fetchall()
        finally:
            connection.close()
        return tuple(self._record_from_row(row) for row in rows)

    def list_all_for_student(self, student_id: str) -> tuple[LearningEventRecord, ...]:
        """Return all facts for replay; never returns another student's facts."""

        self._validate_student_id(student_id)
        migrate_learner_memory_database(self._path)
        connection = connect_sqlite(self._path)
        try:
            rows = connection.execute(
                """SELECT id, student_id, session_id, turn_id, event_type,
                          observed_at, payload_json, schema_version
                   FROM learning_events WHERE student_id = ?
                   ORDER BY observed_at ASC, rowid ASC""",
                (student_id,),
            ).fetchall()
        finally:
            connection.close()
        return tuple(self._record_from_row(row) for row in rows)

    @staticmethod
    def _append_one(connection: sqlite3.Connection, record: LearningEventRecord) -> int:
        values = SQLiteLearningEventRepository._row_values(record)
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO learning_events (
                id, student_id, session_id, turn_id, event_type,
                concept_id, observed_at, payload_json, schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )
        if cursor.rowcount == 1:
            return 1
        existing = connection.execute(
            """
            SELECT id, student_id, session_id, turn_id, event_type,
                   concept_id, observed_at, payload_json, schema_version
            FROM learning_events WHERE id = ?
            """,
            (record.event.event_id,),
        ).fetchone()
        if existing is None or tuple(existing) != values:
            raise ValueError(f"learning event identity conflict: {record.event.event_id}")
        return 0

    @staticmethod
    def _row_values(record: LearningEventRecord) -> tuple[object, ...]:
        event = record.event
        payload = event.to_dict().get("payload", {})
        return (
            event.event_id,
            event.student_id,
            event.session_id,
            record.turn_id,
            event.event_type.value,
            payload.get("concept_id"),
            datetime.fromtimestamp(event.timestamp, timezone.utc).isoformat(),
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            record.schema_version,
        )

    @staticmethod
    def _record_from_row(row: sqlite3.Row) -> LearningEventRecord:
        observed_at = datetime.fromisoformat(str(row["observed_at"]))
        event = BaseEvent.from_dict(
            {
                "event_id": row["id"],
                "student_id": row["student_id"],
                "session_id": row["session_id"],
                "event_type": row["event_type"],
                "timestamp": observed_at.timestamp(),
                "payload": json.loads(row["payload_json"]),
            }
        )
        return LearningEventRecord(
            event=event,
            turn_id=str(row["turn_id"]),
            schema_version=int(row["schema_version"]),
        )

    @classmethod
    def _validate_batch(cls, records: tuple[LearningEventRecord, ...]) -> None:
        student_ids = set()
        for record in records:
            event = record.event
            cls._validate_student_id(event.student_id)
            if not event.event_id.strip():
                raise ValueError("event_id is required")
            if not event.session_id.strip():
                raise ValueError("session_id is required")
            if not record.turn_id.strip():
                raise ValueError("turn_id is required")
            if record.schema_version <= 0:
                raise ValueError("schema_version must be positive")
            student_ids.add(event.student_id)
        if len(student_ids) != 1:
            raise ValueError("an event batch must belong to one student")

    @staticmethod
    def _validate_student_id(student_id: str) -> None:
        if not student_id or not str(student_id).strip():
            raise ValueError("student_id is required")


__all__ = [
    "LearningEventRecord",
    "LearningEventRepository",
    "SQLiteLearningEventRepository",
]
