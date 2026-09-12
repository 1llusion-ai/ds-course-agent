"""SQLite persistence for assigned assessments."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from pathlib import Path

import ds_course_agent.shared.config as config
from ds_course_agent.assessment.records import AssessmentRecord, AssessmentStatus


class AssessmentRepository:
    """Persist complete typed assessment records in one runtime database."""

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path or config.ASSESSMENT_DB_PATH)

    def init_db(self) -> None:
        """Create the assessment table and student/status index."""

        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS assessments (
                    id TEXT PRIMARY KEY,
                    student_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    assigned_at TEXT NOT NULL,
                    opened_at TEXT,
                    submitted_at TEXT,
                    version INTEGER NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_assessments_student_status
                ON assessments(student_id, status, assigned_at DESC)
                """
            )

    def create(self, record: AssessmentRecord) -> None:
        """Insert a newly assigned assessment."""

        self.init_db()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO assessments (
                    id, student_id, status, assigned_at, opened_at,
                    submitted_at, version, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._row_values(record),
            )

    def get(self, assessment_id: str, student_id: str) -> AssessmentRecord | None:
        """Return one assessment owned by the student."""

        self.init_db()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM assessments WHERE id = ? AND student_id = ?",
                (assessment_id, student_id),
            ).fetchone()
        return AssessmentRecord.model_validate_json(row["payload_json"]) if row else None

    def list_for_student(
        self,
        student_id: str,
        statuses: Sequence[AssessmentStatus],
    ) -> tuple[AssessmentRecord, ...]:
        """Return assigned assessments in newest-first order."""

        if not statuses:
            return ()
        self.init_db()
        placeholders = ", ".join("?" for _ in statuses)
        query = (
            "SELECT payload_json FROM assessments "
            f"WHERE student_id = ? AND status IN ({placeholders}) "
            "ORDER BY assigned_at DESC"
        )
        with self._connect() as connection:
            rows = connection.execute(query, (student_id, *(status.value for status in statuses))).fetchall()
        return tuple(AssessmentRecord.model_validate_json(row["payload_json"]) for row in rows)

    def update(self, record: AssessmentRecord, *, expected_version: int) -> bool:
        """Atomically replace a record when its persisted version is unchanged."""

        if record.version != expected_version + 1:
            raise ValueError("updated record version must increment by one")
        self.init_db()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE assessments
                SET status = ?, assigned_at = ?, opened_at = ?, submitted_at = ?,
                    version = ?, payload_json = ?
                WHERE id = ? AND student_id = ? AND version = ?
                """,
                (
                    record.status.value,
                    record.assigned_at.isoformat(),
                    record.opened_at.isoformat() if record.opened_at else None,
                    record.submitted_at.isoformat() if record.submitted_at else None,
                    record.version,
                    record.model_dump_json(),
                    record.id,
                    record.student_id,
                    expected_version,
                ),
            )
        return cursor.rowcount == 1

    def _connect(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _row_values(record: AssessmentRecord) -> tuple[object, ...]:
        return (
            record.id,
            record.student_id,
            record.status.value,
            record.assigned_at.isoformat(),
            record.opened_at.isoformat() if record.opened_at else None,
            record.submitted_at.isoformat() if record.submitted_at else None,
            record.version,
            record.model_dump_json(),
        )
