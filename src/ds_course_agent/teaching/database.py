"""Teaching-owned schema migrations for learner memory facts and projections."""

from __future__ import annotations

from pathlib import Path

import ds_course_agent.shared.config as config
from ds_course_agent.shared.database import Migration, MigrationPlan, SQLiteMigrationRunner

LEARNER_MEMORY_MIGRATIONS = (
    Migration(
        version=1,
        name="create_learner_memory_tables",
        statements=(
            """
            CREATE TABLE learning_events (
                id TEXT PRIMARY KEY,
                student_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                turn_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                concept_id TEXT,
                observed_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                schema_version INTEGER NOT NULL,
                UNIQUE (id, student_id)
            )
            """,
            """
            CREATE INDEX idx_learning_events_student_concept_time
            ON learning_events(student_id, concept_id, observed_at DESC)
            """,
            """
            CREATE INDEX idx_learning_events_student_session_time
            ON learning_events(student_id, session_id, observed_at DESC)
            """,
            """
            CREATE TABLE interaction_episodes (
                id TEXT PRIMARY KEY,
                student_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                turn_id TEXT NOT NULL,
                learner_question TEXT NOT NULL,
                observed_signals_json TEXT NOT NULL,
                inferred_difficulties_json TEXT NOT NULL,
                teaching_approach_json TEXT NOT NULL,
                outcome TEXT NOT NULL DEFAULT 'unknown' CHECK (
                    outcome IN (
                        'unknown',
                        'understood',
                        'continued_clarification',
                        'incorrect_assessment',
                        'correct_assessment',
                        'explicit_negative_feedback',
                        'explicit_positive_feedback'
                    )
                ),
                related_episode_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                extractor_version TEXT NOT NULL,
                UNIQUE (id, student_id),
                FOREIGN KEY (related_episode_id, student_id)
                    REFERENCES interaction_episodes(id, student_id)
            )
            """,
            """
            CREATE INDEX idx_interaction_episodes_student_outcome_time
            ON interaction_episodes(student_id, outcome, updated_at DESC)
            """,
            """
            CREATE TABLE interaction_episode_concepts (
                episode_id TEXT NOT NULL,
                student_id TEXT NOT NULL,
                concept_id TEXT NOT NULL,
                PRIMARY KEY (episode_id, concept_id),
                FOREIGN KEY (episode_id, student_id)
                    REFERENCES interaction_episodes(id, student_id) ON DELETE CASCADE
            )
            """,
            """
            CREATE INDEX idx_episode_concepts_student_concept
            ON interaction_episode_concepts(student_id, concept_id)
            """,
            """
            CREATE TABLE interaction_episode_evidence (
                episode_id TEXT NOT NULL,
                learning_event_id TEXT NOT NULL,
                student_id TEXT NOT NULL,
                PRIMARY KEY (episode_id, learning_event_id),
                FOREIGN KEY (episode_id, student_id)
                    REFERENCES interaction_episodes(id, student_id) ON DELETE CASCADE,
                FOREIGN KEY (learning_event_id, student_id)
                    REFERENCES learning_events(id, student_id) ON DELETE RESTRICT
            )
            """,
            """
            CREATE INDEX idx_episode_evidence_student_event
            ON interaction_episode_evidence(student_id, learning_event_id)
            """,
        ),
    ),
    Migration(
        version=4,
        name="create_learner_profile_snapshots",
        statements=(
            """
            CREATE TABLE learner_profile_snapshots (
                student_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                computed_at TEXT NOT NULL,
                source_event_cursor TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (student_id, version)
            )
            """,
            """
            CREATE INDEX idx_profile_snapshots_student_latest
            ON learner_profile_snapshots(student_id, version DESC)
            """,
        ),
    ),
)


def plan_learner_memory_database(path: str | Path | None = None) -> MigrationPlan:
    """Inspect learner-memory migrations without creating the database."""

    return SQLiteMigrationRunner(path or config.APP_DB_PATH).plan(LEARNER_MEMORY_MIGRATIONS)


def migrate_learner_memory_database(path: str | Path | None = None) -> tuple[Migration, ...]:
    """Apply pending learner-memory migrations to the application database."""

    return SQLiteMigrationRunner(path or config.APP_DB_PATH).apply(LEARNER_MEMORY_MIGRATIONS)


__all__ = [
    "LEARNER_MEMORY_MIGRATIONS",
    "migrate_learner_memory_database",
    "plan_learner_memory_database",
]
