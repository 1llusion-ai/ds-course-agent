"""Teaching-owned maintenance for assessment evidence projections."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import ds_course_agent.shared.config as config
from ds_course_agent.shared.database import connect_sqlite
from ds_course_agent.teaching.database import migrate_learner_memory_database


@dataclass(frozen=True)
class AssessmentEvidenceMaintenanceReport:
    """Counts for one student-scoped assessment evidence operation."""

    student_id: str
    assessment_id: str
    event_count: int
    episode_count: int


class AssessmentEvidenceMaintenance:
    """Preview and delete one assessment's teaching evidence atomically."""

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path or config.APP_DB_PATH)

    def inspect(self, student_id: str, assessment_id: str) -> AssessmentEvidenceMaintenanceReport:
        self._validate_identity(student_id, assessment_id)
        migrate_learner_memory_database(self._path)
        connection = connect_sqlite(self._path)
        try:
            return self._report(connection, student_id, assessment_id)
        finally:
            connection.close()

    def delete(self, student_id: str, assessment_id: str) -> AssessmentEvidenceMaintenanceReport:
        """Delete one assessment's events and projections without touching assessment facts."""

        self._validate_identity(student_id, assessment_id)
        migrate_learner_memory_database(self._path)
        connection = connect_sqlite(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            report = self._report(connection, student_id, assessment_id)
            episode_id = f"assessment_episode:{assessment_id}"
            connection.execute(
                """
                UPDATE interaction_episodes
                SET related_episode_id = NULL
                WHERE student_id = ? AND related_episode_id = ?
                """,
                (student_id, episode_id),
            )
            connection.execute(
                "DELETE FROM interaction_episode_evidence WHERE student_id = ? AND episode_id = ?",
                (student_id, episode_id),
            )
            connection.execute(
                "DELETE FROM interaction_episode_concepts WHERE student_id = ? AND episode_id = ?",
                (student_id, episode_id),
            )
            connection.execute(
                "DELETE FROM interaction_episodes WHERE student_id = ? AND id = ?",
                (student_id, episode_id),
            )
            event_ids = [
                row["id"]
                for row in connection.execute(
                    """
                    SELECT id FROM learning_events
                    WHERE student_id = ? AND event_type = 'question_answered'
                      AND json_extract(payload_json, '$.assessment_id') = ?
                    """,
                    (student_id, assessment_id),
                ).fetchall()
            ]
            if event_ids:
                placeholders = ", ".join("?" for _ in event_ids)
                connection.execute(
                    f"DELETE FROM interaction_episode_evidence WHERE student_id = ? AND learning_event_id IN ({placeholders})",
                    (student_id, *event_ids),
                )
                connection.execute(
                    f"DELETE FROM learning_events WHERE student_id = ? AND id IN ({placeholders})",
                    (student_id, *event_ids),
                )
            connection.commit()
            return report
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _report(connection: sqlite3.Connection, student_id: str, assessment_id: str):
        event_count = connection.execute(
            """
            SELECT COUNT(*) FROM learning_events
            WHERE student_id = ? AND event_type = 'question_answered'
              AND json_extract(payload_json, '$.assessment_id') = ?
            """,
            (student_id, assessment_id),
        ).fetchone()[0]
        episode_count = connection.execute(
            "SELECT COUNT(*) FROM interaction_episodes WHERE student_id = ? AND id = ?",
            (student_id, f"assessment_episode:{assessment_id}"),
        ).fetchone()[0]
        return AssessmentEvidenceMaintenanceReport(student_id, assessment_id, event_count, episode_count)

    @staticmethod
    def _validate_identity(student_id: str, assessment_id: str) -> None:
        if not student_id.strip():
            raise ValueError("student_id is required")
        if not assessment_id.strip():
            raise ValueError("assessment_id is required")


__all__ = ["AssessmentEvidenceMaintenance", "AssessmentEvidenceMaintenanceReport"]
