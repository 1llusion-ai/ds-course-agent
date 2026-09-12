"""Typed assessment lifecycle records and student-facing projections."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ds_course_agent.assessment.models import (
    EvidenceSource,
    GeneratedQuiz,
    GenerateQuestionsRequest,
    QuestionOption,
)


class AssessmentStatus(str, Enum):
    """Finite lifecycle states for an assigned assessment."""

    READY = "ready"
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    EXPIRED = "expired"


class StoredAnswer(BaseModel):
    """One server-owned answer record persisted after submission."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    question_id: str
    selected_option_id: str
    is_correct: bool
    response_time_ms: int = Field(ge=0)
    answer_change_count: int | None = Field(default=None, ge=0)


class AssessmentRecord(BaseModel):
    """Complete persisted assessment, including answer keys and evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    student_id: str
    request: GenerateQuestionsRequest
    quiz: GeneratedQuiz
    question_ids: tuple[str, ...]
    status: AssessmentStatus
    assigned_at: datetime
    opened_at: datetime | None = None
    submitted_at: datetime | None = None
    answers: tuple[StoredAnswer, ...] = ()
    version: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _validate_lifecycle(self) -> AssessmentRecord:
        if len(self.question_ids) != len(self.quiz.questions):
            raise ValueError("question_ids must cover every generated question")
        if len(set(self.question_ids)) != len(self.question_ids):
            raise ValueError("question_ids must be unique")
        if self.status is AssessmentStatus.READY and self.opened_at is not None:
            raise ValueError("ready assessments cannot have opened_at")
        if self.status is AssessmentStatus.IN_PROGRESS and self.opened_at is None:
            raise ValueError("in-progress assessments require opened_at")
        if self.status is AssessmentStatus.SUBMITTED:
            if self.opened_at is None or self.submitted_at is None:
                raise ValueError("submitted assessments require opened_at and submitted_at")
            if len(self.answers) != len(self.question_ids):
                raise ValueError("submitted assessments require one answer per question")
        return self


class AssessmentSummary(BaseModel):
    """Compact assigned-assessment row for the student list."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    title: str
    status: AssessmentStatus
    question_count: int
    assigned_at: datetime
    opened_at: datetime | None


class StudentQuestion(BaseModel):
    """Answer-blind question projection shown while taking an assessment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    stem: str
    options: tuple[QuestionOption, ...]


class StudentAssessment(BaseModel):
    """Answer-blind assessment projection for the assigned student."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    title: str
    status: AssessmentStatus
    assigned_at: datetime
    opened_at: datetime | None
    questions: tuple[StudentQuestion, ...]


class AnswerSubmission(BaseModel):
    """One student answer submitted to the server."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    question_id: str = Field(min_length=1, max_length=64)
    selected_option_id: str = Field(pattern="^[ABCD]$")
    response_time_ms: int = Field(strict=True, ge=0, le=86_400_000)
    answer_change_count: int | None = Field(default=None, strict=True, ge=0, le=10_000)


class SubmitAssessmentRequest(BaseModel):
    """Complete answer set for one assessment submission."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    answers: tuple[AnswerSubmission, ...] = Field(min_length=1)


class QuestionResult(BaseModel):
    """Post-submission result for one question."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    stem: str
    options: tuple[QuestionOption, ...]
    selected_option_id: str
    correct_option_id: str
    is_correct: bool
    explanation: str
    response_time_ms: int
    answer_change_count: int | None
    sources: tuple[EvidenceSource, ...]


class AssessmentResult(BaseModel):
    """Server-scored assessment result available only after submission."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    title: str
    status: AssessmentStatus
    opened_at: datetime
    submitted_at: datetime
    duration_ms: int = Field(ge=0)
    correct_count: int = Field(ge=0)
    question_count: int = Field(ge=1)
    score_percent: float = Field(ge=0, le=100)
    questions: tuple[QuestionResult, ...]
