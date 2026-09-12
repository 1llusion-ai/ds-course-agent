"""Typed candidate feedback shared by assessment acceptance and bounded repair."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ds_course_agent.assessment.models import GeneratedQuestion


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
    QUESTION_COUNT_SHORTFALL = "question_count_shortfall"
    SEMANTIC_DUPLICATE = "semantic_duplicate"
    SOURCE_MISMATCH = "source_mismatch"
    UNCERTAIN_EVIDENCE = "uncertain_evidence"
    UNKNOWN_SOURCE = "unknown_source"


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


@dataclass(frozen=True)
class GenerationGuidance:
    """Preserved accepted questions and actionable feedback for missing slots."""

    accepted_questions: tuple[GeneratedQuestion, ...] = ()
    rejections: tuple[QuestionRejection, ...] = ()
