"""Application service for assigning and completing student assessments."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from threading import RLock
from uuid import uuid4

from ds_course_agent.assessment.feedback import (
    AssessmentGenerationProgress,
    BatchReviewState,
    QuestionRejection,
    QuestionRejectionCode,
)
from ds_course_agent.assessment.generation_constraints import AssessmentExposureConstraint
from ds_course_agent.assessment.items import ReviewedItemRepository, item_identity
from ds_course_agent.assessment.models import GenerateQuestionsRequest
from ds_course_agent.assessment.records import (
    AnswerSubmission,
    AssessmentRecord,
    AssessmentResult,
    AssessmentStatus,
    AssessmentSummary,
    QuestionResult,
    StoredAnswer,
    StudentAssessment,
    StudentQuestion,
)
from ds_course_agent.assessment.repository import AssessmentRepository
from ds_course_agent.assessment.service import (
    AssessmentResourceChangedError,
    AssessmentService,
    AssessmentSlotFailureError,
    get_assessment_service,
)
from ds_course_agent.assessment.versioning import assessment_resource_revision
from ds_course_agent.courses.resources import DEFAULT_COURSE_ID, CourseId
from ds_course_agent.teaching.assessment_assignment import AssessmentPlanContext


class AssessmentNotFoundError(LookupError):
    """The requested assessment does not belong to the current student."""


class AssessmentStateError(RuntimeError):
    """The requested operation is invalid for the assessment lifecycle state."""


class AssessmentSubmissionError(ValueError):
    """The submitted answer set does not match the assigned assessment."""


class AssessmentConcurrencyError(RuntimeError):
    """The assessment changed while a lifecycle transition was being saved."""


class AssessmentApplicationService:
    """Own assignment persistence, answer-blind projection, and server scoring."""

    def __init__(
        self,
        repository: AssessmentRepository | None = None,
        generator: AssessmentService | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
        submission_recorder: Callable[[AssessmentRecord], None] | None = None,
        reviewed_items: ReviewedItemRepository | None = None,
    ) -> None:
        self._repository = repository or AssessmentRepository()
        self._generator = generator
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: str(uuid4()))
        self._lock = RLock()
        self._submission_recorder = submission_recorder
        self._reviewed_items = reviewed_items or ReviewedItemRepository(self._repository.path)
        self._assignment_lock = RLock()

    def assign(
        self,
        student_id: str,
        request: GenerateQuestionsRequest,
        *,
        session_id: str | None = None,
        assignment_id: str | None = None,
        generation_progress: AssessmentGenerationProgress | None = None,
        course_id: CourseId | str = DEFAULT_COURSE_ID,
        plan_context: AssessmentPlanContext | None = None,
    ) -> AssessmentSummary:
        """Serialize allocation so explicit and automatic requests share one owner."""
        with self._assignment_lock:
            return self._assign(
                student_id,
                request,
                session_id=session_id,
                assignment_id=assignment_id,
                generation_progress=generation_progress,
                course_id=course_id,
                plan_context=plan_context,
            )

    def _assign(
        self,
        student_id: str,
        request: GenerateQuestionsRequest,
        *,
        session_id: str | None,
        assignment_id: str | None,
        generation_progress: AssessmentGenerationProgress | None,
        course_id: CourseId | str,
        plan_context: AssessmentPlanContext | None,
    ) -> AssessmentSummary:
        """Reuse reviewed content, fill missing slots, then publish an immutable batch."""

        normalized_course_id = CourseId(course_id)
        if assignment_id is not None:
            existing = self._repository.get(assignment_id, student_id, course_id=normalized_course_id)
            if existing is not None:
                if existing.session_id != session_id or existing.request != request:
                    raise AssessmentStateError("assignment identity conflicts with the persisted request")
                return self._summary(existing)
        if plan_context is not None and plan_context.resource_revision != assessment_resource_revision(
            str(normalized_course_id)
        ):
            raise AssessmentResourceChangedError("frozen assessment plan uses outdated resources")
        active = self._repository.list_for_student(
            student_id, (AssessmentStatus.READY, AssessmentStatus.IN_PROGRESS), course_id=normalized_course_id
        )
        existing_active = next(
            (record for record in active if record.request.target_kc_id == request.target_kc_id), None
        )
        if existing_active is not None:
            return self._summary(existing_active)
        generator = self._generator or get_assessment_service(normalized_course_id)
        revision = assessment_resource_revision(str(normalized_course_id))
        reusable = ()
        exposure = self._exposure(student_id, normalized_course_id, request.target_kc_id)
        generation_options = {
            "exposure": exposure,
            "refresh_exposure": lambda: self._exposure(student_id, normalized_course_id, request.target_kc_id),
        }
        if generation_progress is None:
            history = self._repository.list_for_student(
                student_id, tuple(AssessmentStatus), course_id=normalized_course_id
            )
            seen = tuple(identity for record in reversed(history) for identity in record.item_ids)
            reusable = self._reviewed_items.select(
                request, revision, excluded_item_ids=exposure.excluded_item_ids, recent_item_ids=seen
            )
            quiz = (
                generator.generate(request, reusable_items=reusable, **generation_options)
                if reusable
                else generator.generate(request, **generation_options)
            )
        else:
            quiz = generator.generate(request, progress=generation_progress, **generation_options)
        if len(quiz.questions) != request.count:
            raise AssessmentStateError("assessment generation must return the exact requested question count")
        # Re-read scoped exposure immediately before publication. In-flight
        # changes are normally repaired inside generation; a later race still
        # fails closed with the same bounded, resumable slot protocol.
        exposure = exposure.merge(self._exposure(student_id, normalized_course_id, request.target_kc_id))
        forbidden = {
            index: QuestionRejection(
                (QuestionRejectionCode.RECENT_ITEM_EXPOSURE,),
                question,
                "生成期间此题已出现在当前学生的活跃或近期评估中。",
            )
            for index, question in enumerate(quiz.questions)
            if item_identity(question) in exposure.excluded_item_ids
        }
        if forbidden:
            progress = AssessmentGenerationProgress.build(
                request,
                title=quiz.title,
                evidence=tuple(quiz.sources),
                accepted_by_slot={
                    index: question for index, question in enumerate(quiz.questions) if index not in forbidden
                },
                pending_by_slot=forbidden,
                repair_round=quiz.repair_round,
                resource_revision=quiz.resource_revision,
                review_certificates={
                    index: review for index, review in enumerate(quiz.review_certificates) if index not in forbidden
                },
                exposure=exposure,
                batch_review=BatchReviewState(required=True),
            )
            raise AssessmentSlotFailureError("assessment exposure changed before publication", progress=progress)
        if plan_context is not None and plan_context.resource_revision != assessment_resource_revision(
            str(normalized_course_id)
        ):
            raise AssessmentResourceChangedError("assessment resources changed before publication")
        if quiz.resource_revision == revision:
            self._reviewed_items.accumulate(request, quiz)
        now = self._utc_now()
        record = AssessmentRecord(
            id=assignment_id or self._id_factory(),
            student_id=student_id,
            session_id=session_id,
            request=request,
            plan_context=plan_context,
            quiz=quiz,
            question_ids=tuple(self._id_factory() for _ in quiz.questions),
            item_ids=tuple(item_identity(question) for question in quiz.questions),
            status=AssessmentStatus.READY,
            assigned_at=now,
            course_id=normalized_course_id,
        )
        try:
            self._repository.create(record)
        except sqlite3.IntegrityError:
            existing = self._repository.get(record.id, student_id, course_id=normalized_course_id)
            if existing is None or existing.request != request or existing.session_id != session_id:
                raise
            return self._summary(existing)
        return self._summary(record)

    def _exposure(self, student_id: str, course_id: CourseId, target_kc_id: str) -> AssessmentExposureConstraint:
        history = self._repository.list_for_student(student_id, tuple(AssessmentStatus), course_id=course_id)
        records = {
            record.id: record
            for record in (
                *history[:3],
                *(
                    record
                    for record in history
                    if record.status in {AssessmentStatus.READY, AssessmentStatus.IN_PROGRESS}
                ),
            )
        }
        questions = tuple(question for record in records.values() for question in record.quiz.questions)
        return AssessmentExposureConstraint(
            excluded_item_ids=tuple(sorted({item_identity(question) for question in questions})),
            excluded_questions=tuple(
                question
                for record in records.values()
                if record.request.target_kc_id == target_kc_id
                for question in record.quiz.questions
            ),
        )

    def active_target_kc_ids(self, student_id: str, *, course_id: CourseId | str = DEFAULT_COURSE_ID) -> frozenset[str]:
        """Share active assignment protection with automatic practice scheduling."""
        return frozenset(
            record.request.target_kc_id
            for record in self._repository.list_for_student(
                student_id, (AssessmentStatus.READY, AssessmentStatus.IN_PROGRESS), course_id=course_id
            )
        )

    def list_assessments(
        self,
        student_id: str,
        statuses: Sequence[AssessmentStatus],
        *,
        course_id: CourseId | str = DEFAULT_COURSE_ID,
    ) -> tuple[AssessmentSummary, ...]:
        """List assessments visible to the current student."""

        return tuple(
            self._summary(record)
            for record in self._repository.list_for_student(student_id, statuses, course_id=course_id)
        )

    def open(
        self, assessment_id: str, student_id: str, *, course_id: CourseId | str = DEFAULT_COURSE_ID
    ) -> StudentAssessment:
        """Start an assigned assessment while preserving its first open time."""

        with self._lock:
            record = self._get(assessment_id, student_id, course_id=course_id)
            if record.status is AssessmentStatus.READY:
                record = self._replace(
                    record,
                    status=AssessmentStatus.IN_PROGRESS,
                    opened_at=self._utc_now(),
                )
            elif record.status is not AssessmentStatus.IN_PROGRESS:
                raise AssessmentStateError("only ready or in-progress assessments can be opened")
        return self._student_projection(record)

    def get(
        self, assessment_id: str, student_id: str, *, course_id: CourseId | str = DEFAULT_COURSE_ID
    ) -> StudentAssessment:
        """Return the answer-blind question projection for an active assessment."""

        record = self._get(assessment_id, student_id, course_id=course_id)
        if record.status not in {AssessmentStatus.READY, AssessmentStatus.IN_PROGRESS}:
            raise AssessmentStateError("assessment questions are no longer active")
        return self._student_projection(record)

    def submit(
        self,
        assessment_id: str,
        student_id: str,
        submissions: Sequence[AnswerSubmission],
        *,
        course_id: CourseId | str = DEFAULT_COURSE_ID,
    ) -> AssessmentResult:
        """Idempotently score a complete answer set and persist the terminal result."""

        with self._lock:
            record = self._get(assessment_id, student_id, course_id=course_id)
            if record.status is AssessmentStatus.SUBMITTED:
                self._validate_submissions(record, submissions)
                self._require_same_submission(record, submissions)
                self._record_submission(record)
                return self._result(record)
            if record.status is not AssessmentStatus.IN_PROGRESS:
                raise AssessmentStateError("assessment must be opened before submission")

            by_question_id = self._validate_submissions(record, submissions)
            stored_answers = []
            for question_id, question in zip(record.question_ids, record.quiz.questions, strict=True):
                submitted = by_question_id[question_id]
                stored_answers.append(
                    StoredAnswer(
                        **submitted.model_dump(),
                        is_correct=submitted.selected_option_id == question.correct_option_id,
                    )
                )
            record = self._replace(
                record,
                status=AssessmentStatus.SUBMITTED,
                submitted_at=self._utc_now(),
                answers=tuple(stored_answers),
            )
        self._record_submission(record)
        return self._result(record)

    def result(
        self, assessment_id: str, student_id: str, *, course_id: CourseId | str = DEFAULT_COURSE_ID
    ) -> AssessmentResult:
        """Return answer keys and evidence only after a successful submission."""

        record = self._get(assessment_id, student_id, course_id=course_id)
        if record.status is not AssessmentStatus.SUBMITTED:
            raise AssessmentStateError("assessment result is unavailable before submission")
        return self._result(record)

    def _record_submission(self, record: AssessmentRecord) -> None:
        if self._submission_recorder is not None:
            self._submission_recorder(record)

    def _get(
        self, assessment_id: str, student_id: str, *, course_id: CourseId | str = DEFAULT_COURSE_ID
    ) -> AssessmentRecord:
        record = self._repository.get(assessment_id, student_id, course_id=course_id)
        if record is None:
            raise AssessmentNotFoundError(assessment_id)
        return record

    def _replace(self, record: AssessmentRecord, **updates: object) -> AssessmentRecord:
        updated = record.model_copy(update={**updates, "version": record.version + 1})
        updated = AssessmentRecord.model_validate(updated)
        if not self._repository.update(updated, expected_version=record.version):
            raise AssessmentConcurrencyError("assessment was updated concurrently")
        return updated

    @staticmethod
    def _validate_submissions(
        record: AssessmentRecord,
        submissions: Sequence[AnswerSubmission],
    ) -> dict[str, AnswerSubmission]:
        by_question_id = {submission.question_id: submission for submission in submissions}
        expected_ids = set(record.question_ids)
        if len(by_question_id) != len(submissions):
            raise AssessmentSubmissionError("question answers must not contain duplicates")
        if set(by_question_id) != expected_ids:
            raise AssessmentSubmissionError("submission must answer every assigned question exactly once")
        return by_question_id

    @staticmethod
    def _require_same_submission(
        record: AssessmentRecord,
        submissions: Sequence[AnswerSubmission],
    ) -> None:
        submitted = {
            answer.question_id: (
                answer.selected_option_id,
                answer.response_time_ms,
                answer.answer_change_count,
            )
            for answer in submissions
        }
        persisted = {
            answer.question_id: (
                answer.selected_option_id,
                answer.response_time_ms,
                answer.answer_change_count,
            )
            for answer in record.answers
        }
        if submitted != persisted:
            raise AssessmentStateError("assessment was already submitted with different answers")

    @staticmethod
    def _summary(record: AssessmentRecord) -> AssessmentSummary:
        return AssessmentSummary(
            id=record.id,
            session_id=record.session_id,
            title=record.quiz.title,
            status=record.status,
            question_count=len(record.question_ids),
            assigned_at=record.assigned_at,
            opened_at=record.opened_at,
            course_id=record.course_id,
        )

    @staticmethod
    def _student_projection(record: AssessmentRecord) -> StudentAssessment:
        return StudentAssessment(
            id=record.id,
            title=record.quiz.title,
            status=record.status,
            assigned_at=record.assigned_at,
            opened_at=record.opened_at,
            questions=tuple(
                StudentQuestion(id=question_id, stem=question.stem, options=tuple(question.options))
                for question_id, question in zip(record.question_ids, record.quiz.questions, strict=True)
            ),
            course_id=record.course_id,
        )

    @staticmethod
    def _result(record: AssessmentRecord) -> AssessmentResult:
        if record.opened_at is None or record.submitted_at is None:
            raise AssessmentStateError("submitted assessment timestamps are incomplete")
        sources = {source.id: source for source in record.quiz.sources}
        answers = {answer.question_id: answer for answer in record.answers}
        question_results = []
        for question_id, question in zip(record.question_ids, record.quiz.questions, strict=True):
            answer = answers[question_id]
            question_results.append(
                QuestionResult(
                    id=question_id,
                    stem=question.stem,
                    options=tuple(question.options),
                    selected_option_id=answer.selected_option_id,
                    correct_option_id=question.correct_option_id,
                    is_correct=answer.is_correct,
                    explanation=question.explanation,
                    response_time_ms=answer.response_time_ms,
                    answer_change_count=answer.answer_change_count,
                    sources=tuple(sources[source_id] for source_id in question.source_ids),
                )
            )
        correct_count = sum(answer.is_correct for answer in record.answers)
        duration_ms = max(0, int((record.submitted_at - record.opened_at).total_seconds() * 1000))
        return AssessmentResult(
            id=record.id,
            session_id=record.session_id,
            title=record.quiz.title,
            status=record.status,
            opened_at=record.opened_at,
            submitted_at=record.submitted_at,
            duration_ms=duration_ms,
            correct_count=correct_count,
            question_count=len(record.question_ids),
            score_percent=round(correct_count * 100 / len(record.question_ids), 1),
            questions=tuple(question_results),
            course_id=record.course_id,
        )

    def _utc_now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise ValueError("assessment clock must return a timezone-aware datetime")
        return value.astimezone(timezone.utc)


_application_service: AssessmentApplicationService | None = None
_application_service_lock = RLock()


def get_assessment_application_service() -> AssessmentApplicationService:
    """Return the process-local assignment service; submission observers are injected by callers."""

    global _application_service
    if _application_service is None:
        with _application_service_lock:
            if _application_service is None:
                _application_service = AssessmentApplicationService()
    return _application_service
