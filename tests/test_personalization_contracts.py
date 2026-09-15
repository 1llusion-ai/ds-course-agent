"""Contracts for learner-specific teaching memory."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from ds_course_agent.agent.service import AgentService
from ds_course_agent.shared.query_trace import begin_query_trace, end_query_trace
from ds_course_agent.teaching.interaction_episode_repository import SQLiteInteractionEpisodeRepository
from ds_course_agent.teaching.learner_state import LearnerStateSnapshot
from ds_course_agent.teaching.learning_event_repository import LearningEventRecord, SQLiteLearningEventRepository
from ds_course_agent.teaching.learning_events import QuestionAnsweredEvent
from ds_course_agent.teaching.personalization import (
    EmptyLearnerMemoryRetriever,
    EpisodeOutcome,
    InteractionEpisode,
    SQLiteLearnerMemoryRetriever,
)
from ds_course_agent.teaching.practice import PracticeObservation


def test_empty_retriever_is_student_scoped_and_preserves_target_order() -> None:
    retriever = EmptyLearnerMemoryRetriever()
    learner_state = LearnerStateSnapshot(student_id="student-1")

    context = retriever.retrieve(
        "student-1",
        target_concept_ids=("overfitting", "bias_variance", "overfitting"),
        learner_state=learner_state,
    )

    assert context.target_concept_ids == ("overfitting", "bias_variance")
    assert context.profile_facts == ()
    assert context.assessment_evidence == ()
    assert context.interaction_episodes == ()
    assert context.missing_evidence == ("assessment_evidence", "interaction_episodes")


def test_empty_retriever_rejects_cross_student_state() -> None:
    retriever = EmptyLearnerMemoryRetriever()

    with pytest.raises(ValueError, match="does not belong"):
        retriever.retrieve(
            "student-1",
            target_concept_ids=("overfitting",),
            learner_state=LearnerStateSnapshot(student_id="student-2"),
        )


def test_sqlite_retriever_is_student_and_concept_scoped(tmp_path) -> None:
    repository = SQLiteInteractionEpisodeRepository(tmp_path / "app.db")
    now = datetime.now(timezone.utc)

    def add_episode(episode_id: str, student_id: str, concept_id: str, question: str) -> None:
        repository.save(
            InteractionEpisode(
                episode_id=episode_id,
                student_id=student_id,
                session_id="session",
                turn_id=f"turn-{episode_id}",
                concept_ids=(concept_id,),
                learner_question=question,
                observed_signals=(),
                inferred_difficulties=(),
                teaching_approach=(),
                outcome=EpisodeOutcome.UNKNOWN,
                related_episode_id=None,
                evidence_event_ids=(),
                created_at=now,
                updated_at=now,
                extractor_version="test",
            )
        )

    for index in range(5):
        add_episode(f"episode-{index}", "student-1", "pca", f"问题 {index}")
    add_episode("other-student", "student-2", "pca", "不应返回")
    add_episode("other-concept", "student-1", "svm", "也不应返回")

    context = SQLiteLearnerMemoryRetriever(repository).retrieve(
        "student-1",
        target_concept_ids=("pca",),
        learner_state=LearnerStateSnapshot(student_id="student-1"),
    )
    assert len(context.interaction_episodes) == 3
    assert {episode.student_id for episode in context.interaction_episodes} == {"student-1"}
    assert all(episode.concept_ids == ("pca",) for episode in context.interaction_episodes)


def test_sqlite_retriever_marks_missing_evidence_without_history(tmp_path) -> None:
    context = SQLiteLearnerMemoryRetriever(SQLiteInteractionEpisodeRepository(tmp_path / "app.db")).retrieve(
        "student-1",
        target_concept_ids=("pca",),
        learner_state=LearnerStateSnapshot(student_id="student-1"),
    )
    assert context.interaction_episodes == ()
    assert context.missing_evidence == ("assessment_evidence", "interaction_episodes", "profile_facts")


def test_sqlite_retriever_prioritizes_incorrect_assessment_evidence(tmp_path) -> None:
    path = tmp_path / "app.db"
    events = SQLiteLearningEventRepository(path)

    def answer(event_id: str, question_id: str, *, correct: bool, timestamp: float) -> LearningEventRecord:
        return LearningEventRecord(
            QuestionAnsweredEvent(
                event_id=event_id,
                session_id="assessment-session",
                student_id="student-1",
                timestamp=timestamp,
                observation=PracticeObservation(
                    assessment_id="assessment-1",
                    question_id=question_id,
                    concept_id="pca",
                    display_name="主成分分析",
                    difficulty="intermediate",
                    is_correct=correct,
                    response_time_ms=1000,
                    selected_option_id="B",
                    correct_option_id="A",
                    question_stem="题目内容不进入个性化上下文",
                ),
            ),
            "assessment-turn",
        )

    events.append_many(
        (
            answer("correct-new", "q-correct", correct=True, timestamp=30),
            answer("incorrect-old", "q-incorrect-old", correct=False, timestamp=10),
            answer("incorrect-new", "q-incorrect-new", correct=False, timestamp=20),
        )
    )
    retriever = SQLiteLearnerMemoryRetriever(SQLiteInteractionEpisodeRepository(path), events, lambda _concept: ())
    context = retriever.retrieve(
        "student-1",
        target_concept_ids=("pca",),
        learner_state=LearnerStateSnapshot(student_id="student-1"),
    )

    assert [item.question_id for item in context.assessment_evidence] == ["q-incorrect-new", "q-incorrect-old"]
    assert all(not item.is_correct for item in context.assessment_evidence)


def test_sqlite_retriever_uses_related_concepts_only_as_episode_fallback(tmp_path) -> None:
    path = tmp_path / "app.db"
    repository = SQLiteInteractionEpisodeRepository(path)
    now = datetime.now(timezone.utc)
    for episode_id, concept_id, outcome in (
        ("exact", "pca", EpisodeOutcome.UNKNOWN),
        ("related", "covariance", EpisodeOutcome.CONTINUED_CLARIFICATION),
        ("unrelated", "svm", EpisodeOutcome.EXPLICIT_NEGATIVE_FEEDBACK),
    ):
        repository.save(
            InteractionEpisode(
                episode_id=episode_id,
                student_id="student-1",
                session_id="session",
                turn_id=f"turn-{episode_id}",
                concept_ids=(concept_id,),
                learner_question=episode_id,
                observed_signals=(),
                inferred_difficulties=(),
                teaching_approach=(),
                outcome=outcome,
                related_episode_id=None,
                evidence_event_ids=(),
                created_at=now,
                updated_at=now,
                extractor_version="test",
            )
        )

    retriever = SQLiteLearnerMemoryRetriever(
        repository,
        SQLiteLearningEventRepository(path),
        lambda concept_id: ("covariance",) if concept_id == "pca" else (),
    )
    context = retriever.retrieve(
        "student-1",
        target_concept_ids=("pca",),
        learner_state=LearnerStateSnapshot(student_id="student-1"),
    )

    assert [item.episode_id for item in context.interaction_episodes] == ["exact", "related"]
    assert len(context.profile_facts) + len(context.assessment_evidence) + len(context.interaction_episodes) <= 6


def test_memory_enrichment_records_bounded_trace_counts() -> None:
    service = AgentService.__new__(AgentService)
    service.learner_memory_retriever = EmptyLearnerMemoryRetriever()
    learner_state = LearnerStateSnapshot(student_id="student-1")
    concepts = [SimpleNamespace(concept_id="overfitting")]

    token = begin_query_trace({"entrypoint": "personalization_contract"})
    try:
        context = service._load_personalization_context(
            student_id="student-1",
            matched_concepts=concepts,
            learner_state=learner_state,
        )
    finally:
        trace = end_query_trace(token)

    assert context.target_concept_ids == ("overfitting",)
    result_event = next(item for item in trace["events"] if item["stage"] == "learner_memory.result")
    assert result_event["data"] == {
        "target_concept_count": 1,
        "profile_fact_count": 0,
        "assessment_evidence_count": 0,
        "interaction_episode_count": 0,
        "missing_evidence": ("assessment_evidence", "interaction_episodes"),
    }
    assert any(item["stage"] == "prepare.learner_memory_retrieval" for item in trace["events"])


def test_learning_event_write_records_actual_event_count() -> None:
    from ds_course_agent.agent.routing import ExecutionMode, RouteExecutionResult, RouteFamily, RouteIntent

    service = AgentService.__new__(AgentService)
    calls = []

    def persist_turn(**kwargs):
        calls.append(kwargs)
        return 2

    service.teaching_memory_writer = SimpleNamespace(persist_turn=persist_turn)
    state = SimpleNamespace(
        pending_learning_event=True,
        matched_concepts=[SimpleNamespace(concept_id="overfitting", event_eligible=True)],
        context=SimpleNamespace(original_query="解释过拟合"),
        session_id="session-1",
        student_id="student-1",
        stream_id="turn-1",
        special_case_response=None,
    )
    result = RouteExecutionResult(
        content="回答",
        family=RouteFamily.LEARNING,
        intent=RouteIntent.CONCEPT_QA,
        execution_mode=ExecutionMode.DIRECT_MODEL,
    )

    token = begin_query_trace({"entrypoint": "memory_write_contract"})
    try:
        service._persist_successful_learning_turn(state, result)
    finally:
        trace = end_query_trace(token)

    assert calls[0]["turn_id"] == "turn-1"
    assert "get_memory_core_fn" not in calls[0]
    result_event = next(item for item in trace["events"] if item["stage"] == "learner_memory.write_result")
    assert result_event["data"] == {"storage": "sqlite", "recorded_count": 2}
    assert any(item["stage"] == "memory.learning_event_write" for item in trace["events"])
