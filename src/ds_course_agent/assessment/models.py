"""Typed contracts for textbook-grounded single-choice quiz generation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_KC_ID_LENGTH = 100
MAX_TITLE_LENGTH = 200
MIN_STEM_LENGTH = 6
MAX_STEM_LENGTH = 600
MAX_OPTION_TEXT_LENGTH = 400
MAX_EXPLANATION_LENGTH = 1_500
MAX_SOURCE_ID_LENGTH = 64
MAX_SOURCE_TEXT_LENGTH = 32_000
MAX_SOURCE_REFERENCE_LENGTH = 500
MAX_SOURCE_PAGE = 100_000
MAX_QUESTIONS = 10
OPTION_IDS = frozenset({"A", "B", "C", "D"})
DELIMITER_PAIRS = {
    "(": ")",
    "[": "]",
    "{": "}",
    "（": "）",
    "【": "】",
    "《": "》",
}
DELIMITER_CLOSERS = frozenset(DELIMITER_PAIRS.values())


def _strip_nonblank_text(value: object, *, field_name: str) -> str:
    """Normalize required text before Pydantic applies its length bounds."""

    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    return normalized


def _require_balanced_delimiters(value: str, *, field_name: str) -> str:
    """Reject truncated or malformed text with unbalanced paired delimiters."""

    expected_closers: list[str] = []
    for character in value:
        if character in DELIMITER_PAIRS:
            expected_closers.append(DELIMITER_PAIRS[character])
            continue
        if character not in DELIMITER_CLOSERS:
            continue
        if not expected_closers or expected_closers.pop() != character:
            raise ValueError(f"{field_name} contains unbalanced delimiters")
    if expected_closers:
        raise ValueError(f"{field_name} contains unbalanced delimiters")
    return value


class Difficulty(str, Enum):
    """Supported requested and generated question difficulty levels."""

    BASIC = "basic"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class AssessmentQuestionType(str, Enum):
    """Supported assessment item families."""

    SINGLE_CHOICE = "single_choice"


class CognitiveOperation(str, Enum):
    """Observed thinking required by the item, independent of its requested label."""

    RECALL = "recall"
    INTERPRETATION = "interpretation"
    APPLICATION = "application"
    ANALYSIS = "analysis"


class EvidenceCompleteness(str, Enum):
    """Deterministic completeness state for one assembled evidence span."""

    COMPLETE = "complete"
    NEEDS_PREVIOUS = "needs_previous"
    NEEDS_NEXT = "needs_next"
    NEEDS_BOTH = "needs_both"
    INCOMPLETE = "incomplete"


class FormulaQuality(str, Enum):
    """Structural quality of formulas contained in an evidence span."""

    NOT_APPLICABLE = "not_applicable"
    VALID = "valid"
    MALFORMED = "malformed"
    CONFLICTING = "conflicting"


class AssessmentEvidenceSpan(BaseModel):
    """Server-owned complete evidence assembled from contiguous source chunks."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(strict=True, min_length=1, max_length=MAX_SOURCE_ID_LENGTH)
    text: str = Field(strict=True, min_length=1, max_length=MAX_SOURCE_TEXT_LENGTH)
    source: str | None = Field(default=None, min_length=1, max_length=MAX_SOURCE_REFERENCE_LENGTH)
    page: int | None = Field(default=None, ge=1, le=MAX_SOURCE_PAGE)
    completeness: EvidenceCompleteness
    formulas: tuple[str, ...] = ()
    formula_quality: FormulaQuality


@dataclass(frozen=True)
class DifficultyRule:
    """One shared author instruction and deterministic acceptance policy."""

    operations: frozenset[CognitiveOperation]
    author_instruction: str


DIFFICULTY_RULES = {
    Difficulty.BASIC: DifficultyRule(
        frozenset({CognitiveOperation.RECALL, CognitiveOperation.INTERPRETATION, CognitiveOperation.APPLICATION}),
        "考查学过才能知道的定义、性质、概念区分或单步常规操作；避免题干直接给出答案。",
    ),
    Difficulty.INTERMEDIATE: DifficultyRule(
        frozenset({CognitiveOperation.INTERPRETATION, CognitiveOperation.APPLICATION}),
        "给出具体情境，要求解释关系、比较机制或应用知识做判断；不能仅匹配定义、名称或层级位置。",
    ),
    Difficulty.ADVANCED: DifficultyRule(
        frozenset({CognitiveOperation.ANALYSIS}),
        "给出至少两个需要同时考虑的条件，要求组合教材知识进行多步推理或权衡；不能仅识别定义或列举特征。",
    ),
}


class GenerateQuestionsRequest(BaseModel):
    """Validated input for one grounded quiz-generation request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target_kc_id: str = Field(strict=True, min_length=1, max_length=MAX_KC_ID_LENGTH)
    count: int = Field(default=5, strict=True, ge=1, le=MAX_QUESTIONS)
    difficulty: Difficulty = Difficulty.BASIC
    question_type: AssessmentQuestionType = AssessmentQuestionType.SINGLE_CHOICE

    @field_validator("target_kc_id", mode="before")
    @classmethod
    def _normalize_target_kc_id(cls, value: object) -> str:
        return _strip_nonblank_text(value, field_name="target_kc_id")


class QuestionOption(BaseModel):
    """One labelled answer option in a single-choice question."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(strict=True, min_length=1, max_length=1)
    text: str = Field(strict=True, min_length=1, max_length=MAX_OPTION_TEXT_LENGTH)

    @field_validator("id", mode="before")
    @classmethod
    def _normalize_id(cls, value: object) -> str:
        return _strip_nonblank_text(value, field_name="option id")

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        if value not in OPTION_IDS:
            raise ValueError("option id must be one of A, B, C, D")
        return value

    @field_validator("text", mode="before")
    @classmethod
    def _normalize_text(cls, value: object) -> str:
        return _strip_nonblank_text(value, field_name="option text")

    @field_validator("text")
    @classmethod
    def _validate_text_delimiters(cls, value: str) -> str:
        return _require_balanced_delimiters(value, field_name="option text")


class EvidenceSource(BaseModel):
    """Bounded textbook evidence made visible to the generation model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(strict=True, min_length=1, max_length=MAX_SOURCE_ID_LENGTH)
    text: str = Field(strict=True, min_length=1, max_length=MAX_SOURCE_TEXT_LENGTH)
    source: str | None = Field(default=None, min_length=1, max_length=MAX_SOURCE_REFERENCE_LENGTH)
    page: int | None = Field(default=None, ge=1, le=MAX_SOURCE_PAGE)

    @field_validator("id", "text", mode="before")
    @classmethod
    def _normalize_required_text(cls, value: object, info) -> str:
        return _strip_nonblank_text(value, field_name=info.field_name)

    @field_validator("source", mode="before")
    @classmethod
    def _normalize_source(cls, value: object) -> str | None:
        if value is None:
            return None
        return _strip_nonblank_text(value, field_name="source")

    @field_validator("page", mode="before")
    @classmethod
    def _validate_page_type(cls, value: object) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("page must be an integer")
        return value


class GeneratedQuestion(BaseModel):
    """A structurally valid, source-referenced single-choice question."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stem: str = Field(
        strict=True,
        min_length=MIN_STEM_LENGTH,
        max_length=MAX_STEM_LENGTH,
        description="完整、可独立作答的选择题题干，必须包含具体问题或判断任务，不能仅写主题名称",
    )
    options: list[QuestionOption] = Field(min_length=4, max_length=4)
    correct_option_id: str = Field(strict=True, min_length=1, max_length=1)
    explanation: str = Field(strict=True, min_length=1, max_length=MAX_EXPLANATION_LENGTH)
    difficulty: Difficulty
    source_ids: list[str] = Field(min_length=1, max_length=MAX_QUESTIONS)

    @field_validator("stem", "explanation", "correct_option_id", mode="before")
    @classmethod
    def _normalize_required_text(cls, value: object, info) -> str:
        return _strip_nonblank_text(value, field_name=info.field_name)

    @field_validator("stem", "explanation")
    @classmethod
    def _validate_question_text_delimiters(cls, value: str, info) -> str:
        return _require_balanced_delimiters(value, field_name=info.field_name)

    @field_validator("correct_option_id")
    @classmethod
    def _validate_correct_option_id(cls, value: str) -> str:
        if value not in OPTION_IDS:
            raise ValueError("correct_option_id must be one of A, B, C, D")
        return value

    @field_validator("source_ids", mode="before")
    @classmethod
    def _normalize_source_ids(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        return [_strip_nonblank_text(item, field_name="source id") for item in value]

    @field_validator("source_ids")
    @classmethod
    def _validate_source_ids(cls, value: list[str]) -> list[str]:
        if any(len(source_id) > MAX_SOURCE_ID_LENGTH for source_id in value):
            raise ValueError("source id exceeds its maximum length")
        if len(set(value)) != len(value):
            raise ValueError("source_ids must not contain duplicates")
        return value

    @model_validator(mode="after")
    def _validate_single_choice_shape(self) -> GeneratedQuestion:
        option_ids = [option.id for option in self.options]
        if set(option_ids) != OPTION_IDS or len(set(option_ids)) != len(OPTION_IDS):
            raise ValueError("options must contain exactly one each of A, B, C, D")

        normalized_texts = {" ".join(option.text.split()).casefold() for option in self.options}
        if len(normalized_texts) != len(self.options):
            raise ValueError("option texts must be distinct")
        if self.correct_option_id not in option_ids:
            raise ValueError("correct_option_id must match an option id")
        return self


class QuizDraft(BaseModel):
    """Model-owned quiz fields before the service attaches server-owned evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = Field(
        strict=True,
        min_length=1,
        max_length=MAX_TITLE_LENGTH,
        description="整份测验的简短标题，不是单道题目的题干",
    )
    questions: list[GeneratedQuestion] = Field(min_length=1, max_length=MAX_QUESTIONS)

    @field_validator("title", mode="before")
    @classmethod
    def _normalize_title(cls, value: object) -> str:
        return _strip_nonblank_text(value, field_name="title")


class GeneratedQuiz(BaseModel):
    """Completed grounded quiz with the exact evidence supplied to the model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = Field(
        strict=True,
        min_length=1,
        max_length=MAX_TITLE_LENGTH,
        description="整份测验的简短标题，不是单道题目的题干",
    )
    questions: list[GeneratedQuestion] = Field(min_length=1, max_length=MAX_QUESTIONS)
    sources: list[EvidenceSource] = Field(min_length=1, max_length=MAX_QUESTIONS)

    @field_validator("title", mode="before")
    @classmethod
    def _normalize_title(cls, value: object) -> str:
        return _strip_nonblank_text(value, field_name="title")

    @model_validator(mode="after")
    def _validate_source_ids(self) -> GeneratedQuiz:
        source_ids = [source.id for source in self.sources]
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("sources must have unique ids")
        unknown_source_ids = {
            source_id for question in self.questions for source_id in question.source_ids if source_id not in source_ids
        }
        if unknown_source_ids:
            raise ValueError("questions must only reference returned source ids")
        return self


__all__ = [
    "AssessmentEvidenceSpan",
    "AssessmentQuestionType",
    "Difficulty",
    "EvidenceCompleteness",
    "EvidenceSource",
    "FormulaQuality",
    "GeneratedQuestion",
    "GeneratedQuiz",
    "GenerateQuestionsRequest",
    "QuestionOption",
]
