"""Assessment-owned schema and legacy payload migration."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import ds_course_agent.shared.config as config
from ds_course_agent.shared.database import Migration, MigrationPlan, SQLiteMigrationRunner, connect_sqlite

ASSESSMENT_MIGRATIONS = (
    Migration(
        version=3,
        name="create_normalized_assessment_tables",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS assessments (
                id TEXT PRIMARY KEY,
                student_id TEXT NOT NULL,
                session_id TEXT,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                assigned_at TEXT NOT NULL,
                opened_at TEXT,
                submitted_at TEXT,
                target_kc_id TEXT NOT NULL,
                difficulty TEXT NOT NULL,
                question_type TEXT NOT NULL,
                requested_count INTEGER NOT NULL,
                version INTEGER NOT NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_assessments_student_status
            ON assessments(student_id, status, assigned_at DESC)
            """,
            """
            CREATE TABLE IF NOT EXISTS assessment_questions (
                id TEXT PRIMARY KEY,
                assessment_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                stem TEXT NOT NULL,
                options_json TEXT NOT NULL,
                correct_option_id TEXT NOT NULL,
                explanation TEXT NOT NULL,
                difficulty TEXT NOT NULL,
                source_ids_json TEXT NOT NULL,
                sources_json TEXT NOT NULL,
                UNIQUE (assessment_id, position),
                FOREIGN KEY (assessment_id) REFERENCES assessments(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_assessment_questions_assessment_position
            ON assessment_questions(assessment_id, position)
            """,
            """
            CREATE TABLE IF NOT EXISTS assessment_answers (
                assessment_id TEXT NOT NULL,
                question_id TEXT NOT NULL,
                selected_option_id TEXT NOT NULL,
                is_correct INTEGER NOT NULL CHECK (is_correct IN (0, 1)),
                response_time_ms INTEGER NOT NULL,
                answer_change_count INTEGER,
                submitted_at TEXT NOT NULL,
                PRIMARY KEY (assessment_id, question_id),
                FOREIGN KEY (assessment_id) REFERENCES assessments(id) ON DELETE CASCADE,
                FOREIGN KEY (question_id) REFERENCES assessment_questions(id) ON DELETE CASCADE
            )
            """,
        ),
    ),
)


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}


def _backfill_legacy(connection: sqlite3.Connection) -> int:
    legacy_exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'assessments_legacy'"
    ).fetchone()
    if not legacy_exists:
        return 0
    rows = connection.execute("SELECT payload_json FROM assessments_legacy ORDER BY assigned_at, id").fetchall()
    inserted = 0
    for row in rows:
        payload = json.loads(row["payload_json"])
        if connection.execute("SELECT 1 FROM assessments WHERE id = ?", (payload["id"],)).fetchone():
            continue
        request = payload["request"]
        quiz = payload["quiz"]
        connection.execute(
            """
            INSERT INTO assessments (
                id, student_id, session_id, title, status, assigned_at, opened_at,
                submitted_at, target_kc_id, difficulty, question_type, requested_count, version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["id"],
                payload["student_id"],
                payload.get("session_id"),
                quiz["title"],
                payload["status"],
                payload["assigned_at"],
                payload.get("opened_at"),
                payload.get("submitted_at"),
                request["target_kc_id"],
                request["difficulty"],
                request.get("question_type", "single_choice"),
                request["count"],
                payload["version"],
            ),
        )
        for position, (question_id, question) in enumerate(
            zip(payload["question_ids"], quiz["questions"], strict=True)
        ):
            sources = [source for source in quiz.get("sources", []) if source["id"] in question["source_ids"]]
            connection.execute(
                """
                INSERT INTO assessment_questions (
                    id, assessment_id, position, stem, options_json, correct_option_id,
                    explanation, difficulty, source_ids_json, sources_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    question_id,
                    payload["id"],
                    position,
                    question["stem"],
                    json.dumps(question["options"]),
                    question["correct_option_id"],
                    question["explanation"],
                    question["difficulty"],
                    json.dumps(question["source_ids"]),
                    json.dumps(sources),
                ),
            )
        for answer in payload.get("answers", []):
            connection.execute(
                """
                INSERT INTO assessment_answers (
                    assessment_id, question_id, selected_option_id, is_correct,
                    response_time_ms, answer_change_count, submitted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["id"],
                    answer["question_id"],
                    answer["selected_option_id"],
                    int(answer["is_correct"]),
                    answer["response_time_ms"],
                    answer.get("answer_change_count"),
                    payload["submitted_at"],
                ),
            )
        inserted += 1
    return inserted


def _has_legacy_table(path: Path) -> bool:
    if not path.exists():
        return False
    connection = connect_sqlite(path)
    try:
        return bool(
            connection.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'assessments'").fetchone()
            and "payload_json" in _table_columns(connection, "assessments")
        )
    finally:
        connection.close()


def _migrate_legacy_atomically(path: Path) -> tuple[Migration, ...]:
    runner = SQLiteMigrationRunner(path)
    plan = runner.plan(ASSESSMENT_MIGRATIONS)
    connection = connect_sqlite(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("ALTER TABLE assessments RENAME TO assessments_legacy")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                checksum TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        for migration in plan.pending:
            for statement in migration.statements:
                connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations (version, name, checksum, applied_at) VALUES (?, ?, ?, datetime('now'))",
                (migration.version, migration.name, migration.checksum),
            )
        _backfill_legacy(connection)
        connection.commit()
        return plan.pending
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def migrate_assessment_database(path: str | Path | None = None) -> tuple[Migration, ...]:
    """Apply normalized assessment schema and migrate legacy payload rows once."""

    resolved = Path(path or config.ASSESSMENT_DB_PATH)
    if _has_legacy_table(resolved):
        return _migrate_legacy_atomically(resolved)
    applied = SQLiteMigrationRunner(resolved).apply(ASSESSMENT_MIGRATIONS)
    connection = connect_sqlite(resolved)
    try:
        connection.execute("BEGIN IMMEDIATE")
        _backfill_legacy(connection)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return applied


def plan_assessment_database(path: str | Path | None = None) -> MigrationPlan:
    """Describe pending assessment schema changes without touching the database."""

    resolved = Path(path or config.ASSESSMENT_DB_PATH)
    return SQLiteMigrationRunner(resolved).plan(ASSESSMENT_MIGRATIONS)


__all__ = ["ASSESSMENT_MIGRATIONS", "migrate_assessment_database", "plan_assessment_database"]
