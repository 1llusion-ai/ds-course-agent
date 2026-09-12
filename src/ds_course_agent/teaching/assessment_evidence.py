"""Translate server-scored assessments into durable teaching evidence."""

from __future__ import annotations

from collections.abc import Callable

from ds_course_agent.assessment.records import AssessmentRecord, AssessmentStatus
from ds_course_agent.teaching.learning_events import QuestionAnsweredEvent
from ds_course_agent.teaching.memory_core import MemoryCore, get_memory_core
from ds_course_agent.teaching.practice import PracticeObservation


class AssessmentEvidenceRecorder:
    """Record a submitted assessment idempotently and rebuild the learner profile."""

    def __init__(self, memory_factory: Callable[[], MemoryCore] = get_memory_core) -> None:
        self._memory_factory = memory_factory

    def __call__(self, record: AssessmentRecord) -> None:
        """Publish facts only after the assessment's terminal state is persisted."""

        if record.status is not AssessmentStatus.SUBMITTED or record.submitted_at is None:
            raise ValueError("only submitted assessments provide answer evidence")
        memory = self._memory_factory()
        concept_id = record.request.target_kc_id
        answers = {answer.question_id: answer for answer in record.answers}
        events = []
        for question_id, question in zip(record.question_ids, record.quiz.questions, strict=True):
            answer = answers[question_id]
            events.append(
                QuestionAnsweredEvent(
                    event_id=f"assessment:{record.id}:{question_id}",
                    session_id=record.session_id or f"assessment:{record.id}",
                    student_id=record.student_id,
                    timestamp=record.submitted_at.timestamp(),
                    observation=PracticeObservation(
                        assessment_id=record.id,
                        question_id=question_id,
                        concept_id=concept_id,
                        display_name=concept_id,
                        difficulty=question.difficulty.value,
                        is_correct=answer.is_correct,
                        response_time_ms=answer.response_time_ms,
                        selected_option_id=answer.selected_option_id,
                        correct_option_id=question.correct_option_id,
                        question_stem=question.stem,
                        answer_change_count=answer.answer_change_count,
                    ),
                )
            )
        memory.record_events(tuple(events))
        memory.aggregate_profile(record.student_id)
