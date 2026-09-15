"""Publish server-scored assessment facts into teaching-owned storage."""

from __future__ import annotations

from datetime import timezone

import ds_course_agent.shared.config as config
from ds_course_agent.assessment.records import AssessmentRecord, AssessmentStatus
from ds_course_agent.teaching.interaction_episode_repository import SQLiteInteractionEpisodeRepository
from ds_course_agent.teaching.learning_event_repository import LearningEventRecord, SQLiteLearningEventRepository
from ds_course_agent.teaching.learning_events import QuestionAnsweredEvent
from ds_course_agent.teaching.personalization import EpisodeOutcome, InteractionEpisode
from ds_course_agent.teaching.practice import PracticeObservation


class AssessmentEvidenceRecorder:
    """Record immutable scored answers and one rebuildable assessment episode.

    Assessment evidence has one durable owner: the teaching-owned SQLite
    repositories.
    """

    def __init__(
        self,
        *,
        event_repository: SQLiteLearningEventRepository | None = None,
        episode_repository: SQLiteInteractionEpisodeRepository | None = None,
    ) -> None:
        self._event_repository = event_repository or SQLiteLearningEventRepository(config.APP_DB_PATH)
        self._episode_repository = episode_repository or SQLiteInteractionEpisodeRepository(config.APP_DB_PATH)
        from ds_course_agent.teaching.profile_snapshot_repository import SQLiteProfileSnapshotRepository

        self._profile_repository = SQLiteProfileSnapshotRepository(getattr(self._event_repository, "_path", None))

    def __call__(self, record: AssessmentRecord) -> None:
        if record.status is not AssessmentStatus.SUBMITTED or record.submitted_at is None:
            raise ValueError("only submitted assessments provide answer evidence")

        concept_id = record.request.target_kc_id
        answers = {answer.question_id: answer for answer in record.answers}
        events = tuple(
            self._build_event(record, question_id, question, answers[question_id])
            for question_id, question in zip(record.question_ids, record.quiz.questions, strict=True)
        )
        turn_id = f"assessment:{record.id}"
        self._event_repository.append_many(tuple(LearningEventRecord(event=event, turn_id=turn_id) for event in events))
        now = record.submitted_at.astimezone(timezone.utc)
        outcome = (
            EpisodeOutcome.INCORRECT_ASSESSMENT
            if any(not event.observation.is_correct for event in events)
            else EpisodeOutcome.CORRECT_ASSESSMENT
        )
        episode = InteractionEpisode(
            episode_id=f"assessment_episode:{record.id}",
            student_id=record.student_id,
            session_id=record.session_id or turn_id,
            turn_id=turn_id,
            concept_ids=(concept_id,),
            learner_question=f"assessment:{record.id}",
            observed_signals=("question_answered",),
            inferred_difficulties=(),
            teaching_approach=("assessment",),
            outcome=outcome,
            related_episode_id=None,
            evidence_event_ids=tuple(event.event_id for event in events),
            created_at=now,
            updated_at=now,
            extractor_version="assessment-evidence-v1",
        )
        self._episode_repository.save(episode)
        self._profile_repository.project(record.student_id)

    @staticmethod
    def _build_event(record, question_id, question, answer) -> QuestionAnsweredEvent:
        option_text = {option.id: option.text for option in question.options}
        return QuestionAnsweredEvent(
            event_id=f"assessment:{record.id}:{question_id}",
            session_id=record.session_id or f"assessment:{record.id}",
            student_id=record.student_id,
            timestamp=record.submitted_at.timestamp(),
            observation=PracticeObservation(
                assessment_id=record.id,
                question_id=question_id,
                concept_id=record.request.target_kc_id,
                display_name=record.request.target_kc_id,
                difficulty=question.difficulty.value,
                is_correct=answer.is_correct,
                response_time_ms=answer.response_time_ms,
                selected_option_id=answer.selected_option_id,
                correct_option_id=question.correct_option_id,
                question_stem=question.stem,
                answer_change_count=answer.answer_change_count,
                selected_option_text=option_text.get(answer.selected_option_id),
                correct_option_text=option_text.get(question.correct_option_id),
            ),
        )


__all__ = ["AssessmentEvidenceRecorder"]
