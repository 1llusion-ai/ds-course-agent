"""Typed candidate feedback and resumable progress for assessment generation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ds_course_agent.assessment.models import (
    EvidenceSource,
    GeneratedQuestion,
    GeneratedQuiz,
    GenerateQuestionsRequest,
    question_slot_id,
)


class AssessmentFailureKind(str, Enum):
    """Typed failure categories used by generation and asynchronous preparation."""

    QUESTION_SLOT_FAILURE = "question_slot_failure"
    PROVIDER_TRANSIENT_FAILURE = "provider_transient_failure"
    PROVIDER_PERMANENT_FAILURE = "provider_permanent_failure"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    REVIEWER_UNAVAILABLE = "reviewer_unavailable"
    RETRIEVAL_UNAVAILABLE = "retrieval_unavailable"
    UNKNOWN = "unknown"


RETRYABLE_FAILURE_KINDS = frozenset(
    {
        AssessmentFailureKind.QUESTION_SLOT_FAILURE,
        AssessmentFailureKind.PROVIDER_TRANSIENT_FAILURE,
        AssessmentFailureKind.RETRIEVAL_UNAVAILABLE,
    }
)


def is_assessment_failure_retryable(failure_kind: AssessmentFailureKind) -> bool:
    """Return the explicit retry policy for one typed preparation failure."""

    return failure_kind in RETRYABLE_FAILURE_KINDS


def classify_provider_error(exc: BaseException) -> AssessmentFailureKind:
    """Classify provider failures without treating every invoke exception as transient.

    Network failures, timeouts, rate limits, and HTTP 5xx responses may recover.
    Authentication, client, configuration, and structured-output capability
    errors require a configuration or code change before retrying.
    """

    status_code = _status_code(exc)
    if status_code == 429 or status_code is not None and 500 <= status_code <= 599:
        return AssessmentFailureKind.PROVIDER_TRANSIENT_FAILURE
    if status_code is not None and 400 <= status_code <= 499:
        return AssessmentFailureKind.PROVIDER_PERMANENT_FAILURE

    error_text = " ".join(part.lower() for part in (type(exc).__name__, str(exc)) if part)
    permanent_markers = (
        "authentication",
        "unauthorized",
        "invalid api key",
        "api key",
        "forbidden",
        "permission",
        "bad request",
        "unsupported",
        "not support",
        "structured output",
        "schema",
        "configuration",
        "config",
        "invalid model",
        "model not found",
        "not implemented",
        "validationerror",
        "outputparserexception",
    )
    if any(marker in error_text for marker in permanent_markers):
        return AssessmentFailureKind.PROVIDER_PERMANENT_FAILURE

    transient_markers = (
        "timeout",
        "timed out",
        "connection",
        "connect error",
        "connection reset",
        "dns",
        "rate limit",
        "too many requests",
        "temporarily unavailable",
        "service unavailable",
        "502",
        "503",
        "504",
        "internal server error",
        "server error",
    )
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)) or any(
        marker in error_text for marker in transient_markers
    ):
        return AssessmentFailureKind.PROVIDER_TRANSIENT_FAILURE
    return AssessmentFailureKind.PROVIDER_PERMANENT_FAILURE


def _status_code(exc: BaseException) -> int | None:
    """Read common HTTP status attributes from provider exception wrappers."""

    for candidate in (exc, getattr(exc, "response", None)):
        value = getattr(candidate, "status_code", None)
        if value is None:
            value = getattr(candidate, "status", None)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


class QuestionRejectionCode(str, Enum):
    """Actionable contract and review failures for a candidate or batch."""

    ANSWER_LEAKAGE = "answer_leakage"
    ANSWER_AMBIGUITY = "answer_ambiguity"
    ANSWER_NOT_SUPPORTED = "answer_not_supported"
    DIFFICULTY_MISMATCH = "difficulty_mismatch"
    DUPLICATE_STEM = "duplicate_stem"
    FORMULA_MISMATCH = "formula_mismatch"
    IMPLAUSIBLE_DISTRACTORS = "implausible_distractors"
    INVALID_STRUCTURED_OUTPUT = "invalid_structured_output"
    LOW_PEDAGOGICAL_VALUE = "low_pedagogical_value"
    MULTIPLE_CORRECT_ANSWERS = "multiple_correct_answers"
    OFF_TOPIC = "off_topic"
    PROVIDER_FAILURE = "provider_failure"
    QUESTION_COUNT_SHORTFALL = "question_count_shortfall"
    REVIEWER_UNAVAILABLE = "reviewer_unavailable"
    SEMANTIC_DUPLICATE = "semantic_duplicate"
    SOURCE_MISMATCH = "source_mismatch"
    UNCERTAIN_EVIDENCE = "uncertain_evidence"
    UNKNOWN_SOURCE = "unknown_source"
    UNKNOWN_EVIDENCE_REFERENCE = "unknown_evidence_reference"


@dataclass(frozen=True)
class OptionFeedback:
    """One option's concrete review finding returned to the author."""

    option_id: str
    reason: str


@dataclass(frozen=True)
class QuestionRejection:
    """Rejected candidate and complete repair information; no accepted items."""

    codes: tuple[QuestionRejectionCode, ...]
    question: GeneratedQuestion | None = None
    detail: str = ""
    option_feedback: tuple[OptionFeedback, ...] = ()
    failure_kind: AssessmentFailureKind = AssessmentFailureKind.QUESTION_SLOT_FAILURE

    def __post_init__(self) -> None:
        if not self.codes:
            raise ValueError("question rejection must contain at least one code")
        if any(not isinstance(code, QuestionRejectionCode) for code in self.codes):
            raise TypeError("question rejection codes must use QuestionRejectionCode")
        if len(set(self.codes)) != len(self.codes):
            raise ValueError("question rejection codes must be unique")
        if not isinstance(self.failure_kind, AssessmentFailureKind):
            raise TypeError("question rejection failure_kind must use AssessmentFailureKind")


@dataclass(frozen=True)
class QuestionRepairSlot:
    """One rejected slot included in a single batch editor request."""

    slot_id: str
    slot_index: int
    rejection: QuestionRejection

    def __post_init__(self) -> None:
        if not self.slot_id.strip():
            raise ValueError("slot_id must be nonblank")
        if isinstance(self.slot_index, bool) or not isinstance(self.slot_index, int) or self.slot_index < 0:
            raise ValueError("slot_index must be a non-negative integer")
        if not isinstance(self.rejection, QuestionRejection):
            raise TypeError("repair slot rejection must use QuestionRejection")


@dataclass(frozen=True)
class QuestionRepairRequest:
    """One batch repair request with one shared evidence snapshot."""

    request: GenerateQuestionsRequest
    evidence: tuple[EvidenceSource, ...]
    slots: tuple[QuestionRepairSlot, ...]
    accepted_questions: tuple[GeneratedQuestion, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.request, GenerateQuestionsRequest):
            raise TypeError("repair request must use GenerateQuestionsRequest")
        if not self.evidence:
            raise ValueError("repair evidence must not be empty")
        if any(not isinstance(source, EvidenceSource) for source in self.evidence):
            raise TypeError("repair evidence must use EvidenceSource")
        if not self.slots:
            raise ValueError("repair request must contain at least one slot")
        slot_indices = [slot.slot_index for slot in self.slots]
        if len(set(slot_indices)) != len(slot_indices):
            raise ValueError("repair slot indexes must be unique")
        slot_ids = [slot.slot_id for slot in self.slots]
        if len(set(slot_ids)) != len(slot_ids):
            raise ValueError("repair slot ids must be unique")
        expected_ids = {question_slot_id(self.request.target_kc_id, slot_index) for slot_index in slot_indices}
        if set(slot_ids) != expected_ids:
            raise ValueError("repair slot ids must be stable ids for the requested KC and slot indexes")


class QuestionRepairResult(BaseModel):
    """One model-produced revision addressed to a stable question slot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    slot_id: str = Field(min_length=1)
    question: GeneratedQuestion


class QuestionRepairBatch(BaseModel):
    """Structured output from one editor call covering repaired slots."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    revisions: tuple[QuestionRepairResult, ...] = Field(min_length=1)


@dataclass(frozen=True)
class QuestionSlotFailure:
    """The final typed failure state for one unfilled question slot."""

    slot_index: int
    codes: tuple[QuestionRejectionCode, ...]
    detail: str = ""
    failure_kind: AssessmentFailureKind = AssessmentFailureKind.QUESTION_SLOT_FAILURE

    def __post_init__(self) -> None:
        if isinstance(self.slot_index, bool) or not isinstance(self.slot_index, int) or self.slot_index < 0:
            raise ValueError("slot_index must be a non-negative integer")
        if not self.codes:
            raise ValueError("slot failure must contain at least one code")
        if any(not isinstance(code, QuestionRejectionCode) for code in self.codes):
            raise TypeError("slot failure codes must use QuestionRejectionCode")
        if len(set(self.codes)) != len(self.codes):
            raise ValueError("slot failure codes must be unique")
        if not isinstance(self.failure_kind, AssessmentFailureKind):
            raise TypeError("slot failure failure_kind must use AssessmentFailureKind")


class AcceptedQuestionProgress(BaseModel):
    """One validated question retained across a failed preparation retry."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    slot_id: str = Field(min_length=1)
    slot_index: int = Field(strict=True, ge=0)
    question: GeneratedQuestion


class PendingQuestionProgress(BaseModel):
    """One unfilled slot and its complete typed failure context."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    slot_id: str = Field(min_length=1)
    slot_index: int = Field(strict=True, ge=0)
    rejection_codes: tuple[QuestionRejectionCode, ...] = Field(min_length=1)
    question: GeneratedQuestion | None = None
    detail: str = ""
    option_feedback: tuple[OptionFeedback, ...] = ()
    failure_kind: AssessmentFailureKind = AssessmentFailureKind.QUESTION_SLOT_FAILURE

    @model_validator(mode="after")
    def _validate_codes(self) -> PendingQuestionProgress:
        if len(set(self.rejection_codes)) != len(self.rejection_codes):
            raise ValueError("pending slot rejection codes must be unique")
        return self

    @classmethod
    def from_rejection(
        cls,
        request: GenerateQuestionsRequest,
        slot_index: int,
        rejection: QuestionRejection,
    ) -> PendingQuestionProgress:
        return cls(
            slot_id=question_slot_id(request.target_kc_id, slot_index),
            slot_index=slot_index,
            rejection_codes=rejection.codes,
            question=rejection.question,
            detail=rejection.detail,
            option_feedback=rejection.option_feedback,
            failure_kind=rejection.failure_kind,
        )

    def to_rejection(self) -> QuestionRejection:
        return QuestionRejection(
            self.rejection_codes,
            self.question,
            self.detail,
            self.option_feedback,
            self.failure_kind,
        )


class AssessmentGenerationProgress(BaseModel):
    """Durable, slot-addressed generation state used for exact-count retries."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request: GenerateQuestionsRequest
    title: str = Field(min_length=1)
    evidence: tuple[EvidenceSource, ...] = Field(min_length=1)
    accepted_slots: tuple[AcceptedQuestionProgress, ...] = ()
    pending_slots: tuple[PendingQuestionProgress, ...] = ()
    repair_round: int = Field(default=0, strict=True, ge=0)

    @model_validator(mode="after")
    def _validate_slot_coverage(self) -> AssessmentGenerationProgress:
        accepted_indexes = [item.slot_index for item in self.accepted_slots]
        pending_indexes = [item.slot_index for item in self.pending_slots]
        if len(set(accepted_indexes)) != len(accepted_indexes):
            raise ValueError("accepted progress slots must be unique")
        if len(set(pending_indexes)) != len(pending_indexes):
            raise ValueError("pending progress slots must be unique")
        if set(accepted_indexes) & set(pending_indexes):
            raise ValueError("a progress slot cannot be both accepted and pending")
        expected_indexes = set(range(self.request.count))
        if set(accepted_indexes) | set(pending_indexes) != expected_indexes:
            raise ValueError("generation progress must cover every requested slot")
        expected_ids = {question_slot_id(self.request.target_kc_id, index) for index in expected_indexes}
        actual_ids = {item.slot_id for item in (*self.accepted_slots, *self.pending_slots)}
        if actual_ids != expected_ids:
            raise ValueError("generation progress must use stable slot ids")
        return self

    @property
    def accepted_count(self) -> int:
        return len(self.accepted_slots)

    @property
    def pending_count(self) -> int:
        return len(self.pending_slots)

    @property
    def retryable(self) -> bool:
        return any(is_assessment_failure_retryable(item.failure_kind) for item in self.pending_slots)

    @classmethod
    def build(
        cls,
        request: GenerateQuestionsRequest,
        *,
        title: str,
        evidence: tuple[EvidenceSource, ...],
        accepted_by_slot: dict[int, GeneratedQuestion],
        pending_by_slot: dict[int, QuestionRejection],
        repair_round: int,
    ) -> AssessmentGenerationProgress:
        return cls(
            request=request,
            title=title,
            evidence=evidence,
            accepted_slots=tuple(
                AcceptedQuestionProgress(
                    slot_id=question_slot_id(request.target_kc_id, slot_index),
                    slot_index=slot_index,
                    question=accepted_by_slot[slot_index],
                )
                for slot_index in sorted(accepted_by_slot)
            ),
            pending_slots=tuple(
                PendingQuestionProgress.from_rejection(request, slot_index, rejection)
                for slot_index, rejection in sorted(pending_by_slot.items())
            ),
            repair_round=repair_round,
        )

    @classmethod
    def completed(cls, request: GenerateQuestionsRequest, quiz: GeneratedQuiz) -> AssessmentGenerationProgress:
        if len(quiz.questions) != request.count:
            raise ValueError("completed generation progress requires the exact requested question count")
        return cls.build(
            request,
            title=quiz.title,
            evidence=tuple(quiz.sources),
            accepted_by_slot=dict(enumerate(quiz.questions)),
            pending_by_slot={},
            repair_round=0,
        )

    def accepted_questions(self) -> tuple[GeneratedQuestion, ...]:
        """Return retained questions in their stable slot order."""

        return tuple(item.question for item in self.accepted_slots)


__all__ = [
    "AssessmentFailureKind",
    "AssessmentGenerationProgress",
    "AcceptedQuestionProgress",
    "OptionFeedback",
    "PendingQuestionProgress",
    "QuestionRepairBatch",
    "QuestionRepairRequest",
    "QuestionRepairResult",
    "QuestionRepairSlot",
    "QuestionRejection",
    "QuestionRejectionCode",
    "QuestionSlotFailure",
    "classify_provider_error",
    "is_assessment_failure_retryable",
]
