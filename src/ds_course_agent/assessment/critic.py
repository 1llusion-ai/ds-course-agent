"""Independent pedagogical criticism for structurally valid quiz candidates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import Enum
from threading import RLock
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from ds_course_agent.assessment.generator import AssessmentGenerationError
from ds_course_agent.assessment.models import (
    MAX_EXPLANATION_LENGTH,
    MAX_QUESTIONS,
    OPTION_IDS,
    CognitiveOperation,
    GeneratedQuestion,
    GenerateQuestionsRequest,
)

MAX_CRITIC_PROMPT_CHARS = 24_000
MAX_OPTION_CRITIQUE_REASON_LENGTH = 400
MAX_ITEM_CRITIQUE_REASON_LENGTH = 800

_SYSTEM_PROMPT = """你是独立的选择题命题质量审查员，不负责判断教材证据，也看不到生成器答案和解析。
逐题独立作答，再从尚未掌握当前知识点的学习者视角评价选项。
错误选项本来就不符合正确知识；不能仅用“此选项错误”“学过的人知道答案”判定干扰项无效。
逐项 assessment 只判断该项能否正确回答题干：answer 或 distractor。
若多个选项成立，把它们都判为 answer；若无正确答案，则全部为 distractor。
错误选项的功能与正确选项不同，正是概念辨析的考点；同类操作、相邻概念或参数方向混淆可以是有效干扰。
例如问一种聚合操作的用途，其余同类聚合操作是合理候选，不能仅因它们的用途不同而拒绝。
干扰质量通过可比性和教学缺陷单独判断：明显荒谬、跨领域、无法与题干衔接的选项需指出具体缺陷。
reason 应说明该候选反映的概念区别或实际构造问题，不能只把“答案错误”再算作一个质量缺陷。
same_type_and_granularity 要求该选项与其他选项属于同一概念类别、抽象层级和表达形式。
只有无需掌握知识就能借助长度、措辞或语法锁定答案时，才列入 leakage_signals；普通术语重现不是泄漏。
若题目同义反复、只靠常识、答案已写在题干里或考查不可迁移案例细节，列入 pedagogical_defects。
基础记忆题可以有教学价值，但你看不到请求难度，必须判断题面实际需要的 cognitive_operation：
recall=识别定义/名称/性质/层级位置；interpretation=解释关系或比较机制；
application=把知识用于给定新情境或计算；analysis=同时结合至少两个条件进行多步推理或权衡。
题干长、术语多或选项长都不代表 analysis。把题干已经给出的答案复述一遍属于同义反复缺陷。
还要判断当前题目之间以及与此前已通过题目是否重复学习目标。相同主题或同属一种认知操作不等于重复；
只有实际考查同一事实或同一应用规则，掌握前题就能机械复述答案时才判重复。
每个 reason 必须解释具体依据；所有结论仅针对实际观察到的缺陷，不推测不存在的问题。"""


class AssessmentCritiqueError(AssessmentGenerationError):
    """The pedagogical critic could not return a complete trustworthy review."""


class LeakageSignal(str, Enum):
    """Observable construction cues that can reveal an answer without mastery."""

    LENGTH_OUTLIER = "length_outlier"
    WORDING_ECHO = "wording_echo"
    GRAMMAR_FIT = "grammar_fit"
    SPECIFICITY_OUTLIER = "specificity_outlier"


class PedagogicalDefect(str, Enum):
    """General defects that reduce an item's instructional usefulness."""

    TAUTOLOGY = "tautology"
    COMMON_SENSE_ONLY = "common_sense_only"
    TRIVIAL_LABEL_RECALL = "trivial_label_recall"
    INCIDENTAL_CASE_DETAIL = "incidental_case_detail"
    WEAK_DISTRACTORS = "weak_distractors"
    NONPARALLEL_OPTIONS = "nonparallel_options"


class OptionLeakageSignal(BaseModel):
    """One answer cue tied to the option that receives the unintended advantage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    option_id: str = Field(strict=True, min_length=1, max_length=1)
    signal: LeakageSignal

    @field_validator("option_id", mode="before")
    @classmethod
    def _normalize_option_id(cls, value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("option_id must be nonblank text")
        return value.strip()

    @field_validator("option_id")
    @classmethod
    def _validate_option_id(cls, value: str) -> str:
        if value not in OPTION_IDS:
            raise ValueError("option_id must be one of A, B, C, D")
        return value


class OptionAssessment(str, Enum):
    """One exclusive option role; correctness and distractor quality cannot conflict."""

    ANSWER = "answer"
    DISTRACTOR = "distractor"


class OptionCritique(BaseModel):
    """Pedagogical assessment of one displayed answer option."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    option_id: str = Field(strict=True, min_length=1, max_length=1)
    assessment: OptionAssessment = Field(
        description="answer=能正确回答；distractor=错误候选。干扰质量由可比性和具体教学缺陷独立判断"
    )
    same_type_and_granularity: bool = Field(strict=True)
    reason: str = Field(strict=True, min_length=1, max_length=MAX_OPTION_CRITIQUE_REASON_LENGTH)

    @field_validator("option_id", "reason", mode="before")
    @classmethod
    def _normalize_text(cls, value: object, info) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{info.field_name} must be nonblank text")
        return value.strip()

    @field_validator("option_id")
    @classmethod
    def _validate_option_id(cls, value: str) -> str:
        if value not in OPTION_IDS:
            raise ValueError("option_id must be one of A, B, C, D")
        return value


class ItemCritique(BaseModel):
    """Complete answer-blind pedagogical review for one candidate item."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    question_index: int = Field(strict=True, ge=0, lt=MAX_QUESTIONS)
    option_critiques: list[OptionCritique] = Field(min_length=4, max_length=4)
    leakage_signals: list[OptionLeakageSignal] = Field(max_length=4, json_schema_extra={"uniqueItems": True})
    pedagogical_defects: list[PedagogicalDefect] = Field(max_length=6, json_schema_extra={"uniqueItems": True})
    pedagogically_useful: bool = Field(strict=True)
    cognitive_operation: CognitiveOperation = Field(
        description="只依据题干实际要求判断，不能依据主题的专业程度推测难度"
    )
    distinct_learning_objective: bool = Field(strict=True)
    learning_objective: str = Field(strict=True, min_length=1, max_length=MAX_EXPLANATION_LENGTH)
    reason: str = Field(strict=True, min_length=1, max_length=MAX_ITEM_CRITIQUE_REASON_LENGTH)

    @field_validator("reason", "learning_objective", mode="before")
    @classmethod
    def _normalize_text(cls, value: object, info) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{info.field_name} must be nonblank text")
        return value.strip()

    @property
    def apparent_correct_option_ids(self) -> list[str]:
        """Derive the answer set from option roles rather than asking the model twice."""
        return [option.option_id for option in self.option_critiques if option.assessment is OptionAssessment.ANSWER]

    @model_validator(mode="after")
    def _validate_complete_option_coverage(self) -> ItemCritique:
        option_ids = [critique.option_id for critique in self.option_critiques]
        if set(option_ids) != OPTION_IDS or len(set(option_ids)) != len(OPTION_IDS):
            raise ValueError("option_critiques must contain exactly one each of A, B, C, D")
        leakage_keys = [(item.option_id, item.signal) for item in self.leakage_signals]
        if len(set(leakage_keys)) != len(leakage_keys):
            raise ValueError("leakage_signals must not contain duplicates")
        if len(set(self.pedagogical_defects)) != len(self.pedagogical_defects):
            raise ValueError("pedagogical_defects must not contain duplicates")
        return self


class CritiqueBatch(BaseModel):
    """Complete ordered pedagogical reviews for one candidate batch."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    critiques: list[ItemCritique] = Field(min_length=1, max_length=MAX_QUESTIONS)


class AssessmentQualityCritic:
    """Run one independent answer-blind pedagogical critique call per batch."""

    def __init__(self, model: Any | None = None) -> None:
        self._model = model
        self._model_lock = RLock()

    def critique(
        self,
        request: GenerateQuestionsRequest,
        questions: Sequence[GeneratedQuestion],
        accepted_questions: Sequence[GeneratedQuestion] = (),
    ) -> tuple[ItemCritique, ...]:
        """Return complete ordered critiques or fail closed without hidden retries."""

        if not questions:
            raise AssessmentCritiqueError("at least one candidate question is required")
        messages = self._build_messages(request, questions, accepted_questions)
        structured_model = self._structured_model(self._resolve_model(), len(questions))
        try:
            raw_output = structured_model.invoke(messages)
            batch = self._coerce_batch(raw_output)
        except AssessmentCritiqueError:
            raise
        except Exception as exc:
            raise AssessmentCritiqueError("assessment pedagogical critique failed") from exc

        expected_indices = set(range(len(questions)))
        actual_indices = {critique.question_index for critique in batch.critiques}
        if actual_indices != expected_indices or len(batch.critiques) != len(questions):
            raise AssessmentCritiqueError("assessment critic returned incomplete question coverage")
        return tuple(sorted(batch.critiques, key=lambda critique: critique.question_index))

    def _resolve_model(self) -> Any:
        """Create the configured reviewer model only when criticism is needed."""

        if self._model is not None:
            return self._model
        with self._model_lock:
            if self._model is not None:
                return self._model
            try:
                from ds_course_agent.assessment.model_factory import get_assessment_verifier_model

                self._model = get_assessment_verifier_model()
            except Exception as exc:
                raise AssessmentCritiqueError("assessment critic model is unavailable") from exc
            if self._model is None:
                raise AssessmentCritiqueError("assessment critic model factory returned no model")
        return self._model

    @staticmethod
    def _structured_model(model: Any, question_count: int) -> Any:
        factory = getattr(model, "with_structured_output", None)
        if not callable(factory):
            raise AssessmentCritiqueError("assessment critic model does not support structured output")
        try:
            schema = CritiqueBatch.model_json_schema()
            schema["title"] = f"CritiqueBatchOf{question_count}"
            schema["properties"]["critiques"].update(minItems=question_count, maxItems=question_count)
            schema["$defs"]["ItemCritique"]["properties"]["question_index"]["exclusiveMaximum"] = question_count
            structured_model = factory(schema, method="json_schema")
        except Exception as exc:
            raise AssessmentCritiqueError("assessment critic cannot configure structured output") from exc
        if not callable(getattr(structured_model, "invoke", None)):
            raise AssessmentCritiqueError("structured assessment critic does not provide invoke()")
        return structured_model

    @staticmethod
    def _coerce_batch(raw_output: Any) -> CritiqueBatch:
        if isinstance(raw_output, CritiqueBatch):
            return raw_output
        if isinstance(raw_output, Mapping):
            try:
                return CritiqueBatch.model_validate(dict(raw_output))
            except ValidationError as exc:
                raise AssessmentCritiqueError("assessment critic returned invalid structured output") from exc
        raise AssessmentCritiqueError("structured assessment critique output is not a critique payload")

    @staticmethod
    def _build_messages(
        request: GenerateQuestionsRequest,
        questions: Sequence[GeneratedQuestion],
        accepted_questions: Sequence[GeneratedQuestion],
    ) -> list[Any]:
        from langchain_core.messages import HumanMessage, SystemMessage

        question_blocks = []
        for index, question in enumerate(questions):
            options = "\n".join(f"{option.id}. {option.text}" for option in question.options)
            question_blocks.append(f"[question_index={index}]\n题干：{question.stem}\n选项：\n{options}")
        questions_text = "\n\n".join(question_blocks)
        accepted_blocks = []
        for question in accepted_questions:
            options = "\n".join(f"{option.id}. {option.text}" for option in question.options)
            accepted_blocks.append(f"题干：{question.stem}\n选项：\n{options}")
        accepted_text = "\n\n".join(accepted_blocks) or "无"
        user_prompt = (
            f"目标知识点：{request.target_kc_id}\n\n候选题：\n{questions_text}\n\n此前已通过题目：\n{accepted_text}"
        )
        if len(user_prompt) > MAX_CRITIC_PROMPT_CHARS:
            raise AssessmentCritiqueError("assessment critic prompt exceeds its bounded context")
        return [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=user_prompt)]


__all__ = [
    "AssessmentCritiqueError",
    "AssessmentQualityCritic",
    "CritiqueBatch",
    "OptionAssessment",
    "ItemCritique",
    "LeakageSignal",
    "OptionCritique",
    "OptionLeakageSignal",
    "PedagogicalDefect",
]
