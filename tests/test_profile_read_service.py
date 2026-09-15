from __future__ import annotations

from ds_course_agent.teaching.learning_event_repository import LearningEventRecord, SQLiteLearningEventRepository
from ds_course_agent.teaching.learning_events import build_concept_mentioned_event
from ds_course_agent.teaching.profile_snapshot_repository import (
    SQLiteProfileReadService,
    SQLiteProfileSnapshotRepository,
)


def test_profile_read_service_uses_sqlite_events_not_json_profile(tmp_path) -> None:
    path = tmp_path / "app.db"
    event = build_concept_mentioned_event("session", "student-a", "pca", "PCA", "第7章", "概念理解", 0.9, "PCA")
    SQLiteLearningEventRepository(path).append(LearningEventRecord(event, "turn-1"))
    service = SQLiteProfileReadService(SQLiteProfileSnapshotRepository(path))

    profile = service.get_profile("student-a")
    assert set(profile.recent_concepts) == {"pca"}
    assert service.get_profile_window("student-a", 7).profile.recent_concepts["pca"].display_name == "PCA"


def test_profile_read_service_resolves_weak_spot_in_sqlite(tmp_path) -> None:
    from ds_course_agent.teaching.learning_events import build_clarification_event

    path = tmp_path / "app.db"
    concept = build_concept_mentioned_event("session", "student-a", "pca", "PCA", "第7章", "概念理解", 0.9, "PCA")
    first = build_clarification_event("session", "student-a", "pca", concept.event_id, "simplify_request")
    second = build_clarification_event("session", "student-a", "pca", concept.event_id, "example_request")
    repo = SQLiteLearningEventRepository(path)
    repo.append(LearningEventRecord(concept, "turn-1"))
    repo.append(LearningEventRecord(first, "turn-2"))
    repo.append(LearningEventRecord(second, "turn-3"))
    service = SQLiteProfileReadService(SQLiteProfileSnapshotRepository(path))

    assert service.resolve_active_weak_spot("student-a", "pca").concept_id == "pca"
