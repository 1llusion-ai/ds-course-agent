"""Contracts for event-sourced profile snapshots."""

from __future__ import annotations

import json
import sqlite3

from ds_course_agent.teaching.database import migrate_learner_memory_database
from ds_course_agent.teaching.learning_event_repository import LearningEventRecord, SQLiteLearningEventRepository
from ds_course_agent.teaching.learning_events import build_clarification_event, build_concept_mentioned_event
from ds_course_agent.teaching.profile_snapshot_repository import SQLiteProfileSnapshotRepository


def test_profile_snapshot_replays_sqlite_events_and_is_idempotent(tmp_path) -> None:
    path = tmp_path / "app.db"
    events = SQLiteLearningEventRepository(path)
    concept = build_concept_mentioned_event(
        "session", "student-a", "pca", "主成分分析", "第7章", "概念理解", 0.9, "什么是 PCA？"
    )
    concept.timestamp = 100
    clarification = build_clarification_event("session", "student-a", "pca", concept.event_id, "example_request")
    clarification.timestamp = 110
    events.append_many((LearningEventRecord(concept, "turn-1"), LearningEventRecord(clarification, "turn-2")))

    repository = SQLiteProfileSnapshotRepository(path)
    first = repository.project("student-a")
    second = repository.project("student-a")

    assert first == second
    assert first.version == 1
    assert first.source_event_cursor == clarification.event_id
    assert list(first.profile.recent_concepts) == ["pca"]
    assert first.profile.pending_weak_spots[0].concept_id == "pca"


def test_profile_snapshot_is_student_scoped_and_changes_after_new_fact(tmp_path) -> None:
    path = tmp_path / "app.db"
    events = SQLiteLearningEventRepository(path)
    first = build_concept_mentioned_event("session", "student-a", "pca", "PCA", "第7章", "概念理解", 0.9, "PCA")
    other = build_concept_mentioned_event("session", "student-b", "svm", "SVM", "第6章", "概念理解", 0.9, "SVM")
    events.append(LearningEventRecord(first, "turn-1"))
    events.append(LearningEventRecord(other, "turn-2"))
    repository = SQLiteProfileSnapshotRepository(path)
    snapshot = repository.project("student-a")
    assert set(snapshot.profile.recent_concepts) == {"pca"}

    new = build_concept_mentioned_event("session", "student-a", "svm", "SVM", "第6章", "概念理解", 0.9, "SVM")
    events.append(LearningEventRecord(new, "turn-3"))
    updated = repository.project("student-a")
    assert updated.version == 2
    assert set(updated.profile.recent_concepts) == {"pca", "svm"}

    with sqlite3.connect(path) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM learner_profile_snapshots WHERE student_id = 'student-b'"
            ).fetchone()[0]
            == 0
        )


def test_profile_snapshot_reads_legacy_practice_fields(tmp_path) -> None:
    path = tmp_path / "app.db"
    migrate_learner_memory_database(path)
    payload = {
        "student_id": "student-legacy",
        "practice": {
            "overfitting": {
                "concept_id": "overfitting",
                "display_name": "过拟合",
                "answered_count": 1,
                "correct_count": 0,
                "assessment_count": 1,
                "recent_correct_count": 0,
                "recent_answered_count": 1,
                "last_answered_at": 100.0,
                "level": "needs_practice",
                "last_incorrect_stem": "哪个模型发生了过拟合？",
                "recent_attempts": [
                    {
                        "question_stem": "哪个模型发生了过拟合？",
                        "is_correct": False,
                        "selected_option_text": "模型 A",
                        "correct_option_text": "模型 B",
                        "assistance": "unknown",
                    }
                ],
                "unassisted_answered_count": 0,
                "unknown_assistance_count": 1,
            }
        },
    }
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO learner_profile_snapshots "
            "(student_id, course_id, version, computed_at, source_event_cursor, payload_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                "student-legacy",
                "data-science-intro",
                1,
                "2026-11-20T00:00:00+00:00",
                "legacy-event",
                json.dumps(payload),
            ),
        )

    snapshot = SQLiteProfileSnapshotRepository(path).get_latest("student-legacy")

    assert snapshot is not None
    attempt = snapshot.profile.practice["overfitting"].recent_attempts[0]
    assert attempt.selected_option_text == "模型 A"
    assert not hasattr(attempt, "assistance")
