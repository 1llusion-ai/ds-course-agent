"""SQLite learning-event repository contracts."""

from __future__ import annotations

from dataclasses import replace

import pytest

from ds_course_agent.teaching.learning_event_repository import (
    LearningEventRecord,
    SQLiteLearningEventRepository,
)
from ds_course_agent.teaching.learning_events import (
    ConceptMentionedEvent,
    EventType,
    QuestionAnsweredEvent,
)
from ds_course_agent.teaching.practice import PracticeObservation


def _concept_event(
    event_id: str,
    student_id: str,
    concept_id: str,
    *,
    timestamp: float,
) -> ConceptMentionedEvent:
    return ConceptMentionedEvent(
        event_id=event_id,
        session_id=f"session-{student_id}",
        student_id=student_id,
        timestamp=timestamp,
        payload={
            "concept_id": concept_id,
            "concept_name": concept_id,
            "chapter": "第6章",
            "question_type": "概念理解",
            "matched_score": 0.9,
            "raw_question": f"什么是{concept_id}",
        },
    )


def test_append_and_list_are_idempotent_and_student_scoped(tmp_path) -> None:
    repository = SQLiteLearningEventRepository(tmp_path / "app.db")
    student_a = LearningEventRecord(_concept_event("event-a", "student-a", "pca", timestamp=10.0), "turn-a")
    student_b = LearningEventRecord(_concept_event("event-b", "student-b", "svm", timestamp=20.0), "turn-b")

    assert repository.append(student_a) is True
    assert repository.append(student_a) is False
    assert repository.append(student_b) is True

    loaded = repository.list_for_student("student-a")

    assert len(loaded) == 1
    assert loaded[0].turn_id == "turn-a"
    assert loaded[0].schema_version == 1
    assert loaded[0].event.to_dict() == student_a.event.to_dict()


def test_list_filters_by_concept_and_orders_newest_first(tmp_path) -> None:
    repository = SQLiteLearningEventRepository(tmp_path / "app.db")
    repository.append_many(
        (
            LearningEventRecord(_concept_event("old-pca", "student-a", "pca", timestamp=10.0), "turn-1"),
            LearningEventRecord(_concept_event("new-svm", "student-a", "svm", timestamp=30.0), "turn-3"),
            LearningEventRecord(_concept_event("new-pca", "student-a", "pca", timestamp=20.0), "turn-2"),
        )
    )

    all_events = repository.list_for_student("student-a")
    pca_events = repository.list_for_student(
        "student-a",
        event_types=(EventType.CONCEPT_MENTIONED,),
        concept_ids=("pca",),
        limit=2,
    )

    assert [record.event.event_id for record in all_events] == ["new-svm", "new-pca", "old-pca"]
    assert [record.event.event_id for record in pca_events] == ["new-pca", "old-pca"]


def test_question_answered_event_round_trips_as_typed_evidence(tmp_path) -> None:
    repository = SQLiteLearningEventRepository(tmp_path / "app.db")
    event = QuestionAnsweredEvent(
        event_id="assessment:a1:q1",
        session_id="session-a",
        student_id="student-a",
        timestamp=40.0,
        observation=PracticeObservation(
            assessment_id="a1",
            question_id="q1",
            concept_id="decision_tree",
            display_name="决策树",
            difficulty="intermediate",
            is_correct=False,
            response_time_ms=1200,
            selected_option_id="b",
            correct_option_id="a",
            question_stem="决策树如何选择划分？",
        ),
    )

    repository.append(LearningEventRecord(event, "assessment-turn"))
    loaded = repository.list_for_student("student-a")

    assert len(loaded) == 1
    assert isinstance(loaded[0].event, QuestionAnsweredEvent)
    assert loaded[0].event.observation == event.observation


def test_identity_conflict_rolls_back_the_whole_batch(tmp_path) -> None:
    repository = SQLiteLearningEventRepository(tmp_path / "app.db")
    original = LearningEventRecord(_concept_event("existing", "student-a", "pca", timestamp=10.0), "turn-1")
    repository.append(original)
    changed_event = replace(original.event, payload={**original.event.payload, "concept_name": "changed"})

    with pytest.raises(ValueError, match="identity conflict"):
        repository.append_many(
            (
                LearningEventRecord(_concept_event("should-rollback", "student-a", "svm", timestamp=20.0), "turn-2"),
                LearningEventRecord(changed_event, "turn-1"),
            )
        )

    assert [record.event.event_id for record in repository.list_for_student("student-a")] == ["existing"]


def test_batch_rejects_mixed_students_before_creating_database(tmp_path) -> None:
    path = tmp_path / "app.db"
    repository = SQLiteLearningEventRepository(path)

    with pytest.raises(ValueError, match="one student"):
        repository.append_many(
            (
                LearningEventRecord(_concept_event("event-a", "student-a", "pca", timestamp=10.0), "turn-a"),
                LearningEventRecord(_concept_event("event-b", "student-b", "pca", timestamp=10.0), "turn-b"),
            )
        )

    assert not path.exists()


@pytest.mark.parametrize("student_id", ["", None])
def test_student_identity_is_required_for_reads(tmp_path, student_id) -> None:
    repository = SQLiteLearningEventRepository(tmp_path / "app.db")

    with pytest.raises(ValueError, match="student_id is required"):
        repository.list_for_student(student_id)
