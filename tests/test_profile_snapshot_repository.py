"""Contracts for event-sourced profile snapshots."""

from __future__ import annotations

import sqlite3

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
