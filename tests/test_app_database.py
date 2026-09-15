"""Application database migration and learner-memory schema contracts."""

from __future__ import annotations

import sqlite3

import pytest

from ds_course_agent.shared.database import Migration, SQLiteMigrationRunner
from ds_course_agent.teaching.database import (
    LEARNER_MEMORY_MIGRATIONS,
    migrate_learner_memory_database,
    plan_learner_memory_database,
)


def test_migration_dry_run_does_not_create_database(tmp_path) -> None:
    path = tmp_path / "app.db"

    plan = plan_learner_memory_database(path)

    assert plan.applied_versions == ()
    assert [migration.version for migration in plan.pending] == [1, 4]
    assert not path.exists()


def test_learner_memory_schema_applies_once_and_is_inspectable(tmp_path) -> None:
    path = tmp_path / "app.db"

    first = migrate_learner_memory_database(path)
    second = migrate_learner_memory_database(path)
    plan = plan_learner_memory_database(path)

    assert [migration.version for migration in first] == [1, 4]
    assert second == ()
    assert plan.applied_versions == (1, 4)
    assert plan.pending == ()

    with sqlite3.connect(path) as connection:
        tables = {
            row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        migration_rows = connection.execute(
            "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
        ).fetchall()

    assert {
        "schema_migrations",
        "learning_events",
        "interaction_episodes",
        "interaction_episode_concepts",
        "interaction_episode_evidence",
        "learner_profile_snapshots",
    } <= tables
    assert migration_rows == [
        (1, "create_learner_memory_tables", LEARNER_MEMORY_MIGRATIONS[0].checksum),
        (4, "create_learner_profile_snapshots", LEARNER_MEMORY_MIGRATIONS[1].checksum),
    ]


def test_episode_evidence_foreign_keys_reject_cross_student_links(tmp_path) -> None:
    path = tmp_path / "app.db"
    migrate_learner_memory_database(path)

    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        connection.execute(
            """
            INSERT INTO learning_events (
                id, student_id, session_id, turn_id, event_type,
                concept_id, observed_at, payload_json, schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("event-1", "student-a", "session-a", "turn-a", "concept_mentioned", "pca", "now", "{}", 1),
        )
        connection.execute(
            """
            INSERT INTO interaction_episodes (
                id, student_id, session_id, turn_id, learner_question,
                observed_signals_json, inferred_difficulties_json,
                teaching_approach_json, outcome, created_at, updated_at,
                extractor_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "episode-1",
                "student-b",
                "session-b",
                "turn-b",
                "question",
                "[]",
                "[]",
                "[]",
                "unknown",
                "now",
                "now",
                "v1",
            ),
        )

        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            connection.execute(
                """
                INSERT INTO interaction_episode_evidence (
                    episode_id, learning_event_id, student_id
                ) VALUES (?, ?, ?)
                """,
                ("episode-1", "event-1", "student-b"),
            )
    finally:
        connection.close()


def test_applied_migration_definition_cannot_change(tmp_path) -> None:
    path = tmp_path / "app.db"
    runner = SQLiteMigrationRunner(path)
    runner.apply(LEARNER_MEMORY_MIGRATIONS)
    changed = Migration(
        version=1,
        name="create_learner_memory_tables",
        statements=("CREATE TABLE changed_definition (id TEXT PRIMARY KEY)",),
    )

    with pytest.raises(ValueError, match="no longer matches"):
        runner.plan((changed,))


def test_failed_migration_rolls_back_its_schema_changes(tmp_path) -> None:
    path = tmp_path / "app.db"
    runner = SQLiteMigrationRunner(path)
    broken = Migration(
        version=1,
        name="broken",
        statements=(
            "CREATE TABLE should_rollback (id TEXT PRIMARY KEY)",
            "INSERT INTO missing_table (id) VALUES ('x')",
        ),
    )

    with pytest.raises(sqlite3.OperationalError, match="missing_table"):
        runner.apply((broken,))

    with sqlite3.connect(path) as connection:
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'should_rollback'"
        ).fetchone()
        applied_count = connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
    assert table is None
    assert applied_count == 0
