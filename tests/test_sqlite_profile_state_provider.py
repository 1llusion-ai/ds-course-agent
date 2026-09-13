from __future__ import annotations

from ds_course_agent.teaching.learner_state import SQLiteProfileLearnerStateProvider
from ds_course_agent.teaching.learning_event_repository import LearningEventRecord, SQLiteLearningEventRepository
from ds_course_agent.teaching.learning_events import build_concept_mentioned_event
from ds_course_agent.teaching.profile_snapshot_repository import SQLiteProfileSnapshotRepository


def test_sqlite_profile_provider_reads_projected_state(tmp_path) -> None:
    path = tmp_path / "app.db"
    event = build_concept_mentioned_event("session", "student-a", "pca", "PCA", "第7章", "概念理解", 0.9, "PCA")
    SQLiteLearningEventRepository(path).append(LearningEventRecord(event, "turn-1"))
    snapshots = SQLiteProfileSnapshotRepository(path)
    snapshots.project("student-a")

    state = SQLiteProfileLearnerStateProvider(snapshots).get_state("student-a")
    assert state.provider == "sqlite_profile_snapshot"
    assert state.model_version == "snapshot-v1"
    assert set(state.recent_concepts) == {"pca"}


def test_sqlite_profile_provider_falls_back_without_sqlite_facts(tmp_path) -> None:
    class Fallback:
        def get_state(self, student_id, concept_ids=()):
            from ds_course_agent.teaching.learner_state import LearnerStateSnapshot

            return LearnerStateSnapshot(student_id=student_id, provider="fallback")

    state = SQLiteProfileLearnerStateProvider(
        SQLiteProfileSnapshotRepository(tmp_path / "app.db"), Fallback()
    ).get_state("student-a")
    assert state.provider == "fallback"
