"""Evidence-grounded quality verification for generated assessment questions."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from threading import RLock
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ds_course_agent.assessment.formulas import analyze_formula_quality
from ds_course_agent.assessment.generator import AssessmentGenerationError
from ds_course_agent.assessment.models import (
    MAX_EXPLANATION_LENGTH,
    MAX_QUESTIONS,
    OPTION_IDS,
    EvidenceSource,
    GeneratedQuestion,
    GenerateQuestionsRequest,
)

_SYSTEM_PROMPT = """你是《数据科学导论》的严格测验盲审员，不生成或改写题目。
你看不到生成器标记的答案和解析，必须只依据教材证据独立作答。对每道题列出所有能被教材证据
支持为正确答案的选项；每个选项都必须选择一个系统提供的 excerpt_id，不得创造新的编号。
来源归属由系统根据片段编号确定，不要输出 source_id。不要为了满足单选题格式而只挑一个：如果多个选项都成立，就全部列出；如果没有选项能由
证据支持，就返回空列表。
必须结合题干的全部条件判断选项能否回答当前问题，包括否定、范围和比较要求。
教材中出现过的正确事实，如果回答的是另一个问题或不满足题干条件，不能列为该题正确答案。
同时判断题目是否考查请求主题。answer_explanation 必须向学生解释正确选项为什么成立，不能只说题目符合主题，不讨论审核流程或内部编号。
每个结果必须对应当前候选题的 question_index。"""

MAX_EXCERPT_ID_LENGTH = 32
MAX_EVIDENCE_EXCERPT_CHARS = 1_200
MAX_VERIFIER_PROMPT_CHARS = 48_000
_MACHINE_REFERENCE = re.compile(r"(?<![A-Za-z0-9_])([ES])(\d+)(?![A-Za-z0-9_])")
_CITATION_TOKEN = r"(?:\[\s*[ES]\d+\s*\]|(?<![A-Za-z0-9_])[ES]\d+(?![A-Za-z0-9_]))"
_CITATION_SEQUENCE = rf"{_CITATION_TOKEN}(?:\s*(?:和|、|及|与|/|,|，)\s*{_CITATION_TOKEN})*"
_ACCORDING_TO_CITATIONS = re.compile(rf"根据\s*(?:教材证据\s*)?{_CITATION_SEQUENCE}")
_TEXTBOOK_CITATIONS = re.compile(rf"教材证据\s*{_CITATION_SEQUENCE}")
_CITATIONS_BEFORE_REPORTING_VERB = re.compile(rf"{_CITATION_SEQUENCE}(?=\s*(?:明确)?(?:指出|提到|强调|说明|显示|表明))")
_ANY_CITATION = re.compile(_CITATION_TOKEN)
_EMPTY_PARENTHESES = re.compile(r"(?:（\s*）|\(\s*\))")


class AssessmentVerificationError(AssessmentGenerationError):
    """The quality verifier could not produce a complete trustworthy verdict."""


@dataclass(frozen=True)
class EvidenceExcerpt:
    """One server-owned evidence span addressable by the verifier."""

    id: str
    source_id: str
    text: str


@dataclass(frozen=True)
class EvidenceExcerptCatalog:
    """Immutable excerpt address space for one selected evidence snapshot."""

    sources: tuple[EvidenceSource, ...]
    excerpts: tuple[EvidenceExcerpt, ...]

    def __post_init__(self) -> None:
        source_ids = [source.id for source in self.sources]
        excerpt_ids = [excerpt.id for excerpt in self.excerpts]
        if not self.sources or not self.excerpts:
            raise AssessmentVerificationError("evidence catalog must not be empty")
        if len(set(source_ids)) != len(source_ids):
            raise AssessmentVerificationError("evidence source ids must be unique")
        if len(set(excerpt_ids)) != len(excerpt_ids):
            raise AssessmentVerificationError("evidence excerpt ids must be unique")
        known_source_ids = set(source_ids)
        if any(excerpt.source_id not in known_source_ids for excerpt in self.excerpts):
            raise AssessmentVerificationError("evidence excerpt references an unknown source")
        if any(not excerpt.text or len(excerpt.text) > MAX_EVIDENCE_EXCERPT_CHARS for excerpt in self.excerpts):
            raise AssessmentVerificationError("evidence excerpt text is empty or too long")

    @classmethod
    def from_sources(cls, sources: Sequence[EvidenceSource]) -> EvidenceExcerptCatalog:
        """Create stable IDs from the non-empty lines selected by assessment evidence."""

        source_tuple = tuple(sources)
        excerpts = []
        for source in source_tuple:
            for line in source.text.splitlines():
                text = line.strip()
                if not text:
                    continue
                excerpts.append(EvidenceExcerpt(id=f"E{len(excerpts) + 1}", source_id=source.id, text=text))
        return cls(sources=source_tuple, excerpts=tuple(excerpts))

    def validate_verdicts(
        self,
        verdicts: Sequence[EvidenceVerificationVerdict],
        questions: Sequence[GeneratedQuestion],
    ) -> None:
        """Validate every model-selected option and excerpt against this snapshot."""

        excerpt_ids = {excerpt.id for excerpt in self.excerpts}
        for verdict, question in zip(verdicts, questions, strict=True):
            option_ids = {option.id for option in question.options}
            seen_supports: set[tuple[str, str]] = set()
            for support in verdict.supported_options:
                support_key = (support.option_id, support.excerpt_id)
                if support_key in seen_supports:
                    raise AssessmentVerificationError("assessment verifier duplicated option evidence")
                seen_supports.add(support_key)
                if support.option_id not in option_ids or support.excerpt_id not in excerpt_ids:
                    raise AssessmentVerificationError("assessment verifier referenced unknown option or excerpt")

    def source_id_for(self, excerpt_id: str) -> str:
        """Resolve source ownership from the immutable catalog, never model output."""
        for excerpt in self.excerpts:
            if excerpt.id == excerpt_id:
                return excerpt.source_id
        raise AssessmentVerificationError("assessment verifier referenced unknown excerpt")

    def excerpt_for(self, excerpt_id: str) -> EvidenceExcerpt:
        """Return immutable excerpt text for deterministic acceptance gates."""
        for excerpt in self.excerpts:
            if excerpt.id == excerpt_id:
                return excerpt
        raise AssessmentVerificationError("assessment verifier referenced unknown excerpt")

    def student_explanation(self, explanation: str) -> str:
        """Remove validated machine citations from student-facing explanation prose."""

        known_excerpt_ids = {excerpt.id for excerpt in self.excerpts}
        known_source_ids = {source.id for source in self.sources}
        for match in _MACHINE_REFERENCE.finditer(explanation):
            reference = match.group(0)
            known_ids = known_excerpt_ids if match.group(1) == "E" else known_source_ids
            if reference not in known_ids:
                raise AssessmentVerificationError("assessment explanation referenced unknown evidence")

        public_text = _ACCORDING_TO_CITATIONS.sub("根据教材内容", explanation)
        public_text = _TEXTBOOK_CITATIONS.sub("教材内容", public_text)
        public_text = _CITATIONS_BEFORE_REPORTING_VERB.sub("教材", public_text)
        public_text = _ANY_CITATION.sub("", public_text)
        public_text = _EMPTY_PARENTHESES.sub("", public_text)
        return public_text.strip()

    def formulas_for_sources(self, source_ids: set[str]) -> set[str]:
        """Return only structurally valid formulas from the named sources."""
        formulas: set[str] = set()
        for excerpt in self.excerpts:
            if excerpt.source_id not in source_ids:
                continue
            extracted, quality = analyze_formula_quality(excerpt.text)
            if quality.value == "valid":
                formulas.update(extracted)
        return formulas


class OptionEvidence(BaseModel):
    """Server-addressed textbook support for one potentially correct option."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    option_id: str = Field(strict=True, min_length=1, max_length=1)
    excerpt_id: str = Field(strict=True, min_length=1, max_length=MAX_EXCERPT_ID_LENGTH)

    @field_validator("option_id", "excerpt_id", mode="before")
    @classmethod
    def _normalize_text(cls, value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("option evidence fields must be nonblank text")
        return value.strip()

    @field_validator("option_id")
    @classmethod
    def _validate_option_id(cls, value: str) -> str:
        if value not in OPTION_IDS:
            raise ValueError("option_id must be one of A, B, C, D")
        return value


class EvidenceVerificationVerdict(BaseModel):
    """Blind evidence-support analysis for one candidate question."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    question_index: int = Field(strict=True, ge=0, lt=MAX_QUESTIONS)
    supported_options: list[OptionEvidence] = Field(default_factory=list, max_length=8)
    on_topic: bool = Field(strict=True)
    answer_explanation: str = Field(
        strict=True,
        min_length=1,
        max_length=MAX_EXPLANATION_LENGTH,
        description="向学生解释支持选项为什么能回答题干；不是主题相关性的说明",
    )

    @field_validator("answer_explanation", mode="before")
    @classmethod
    def _normalize_text(cls, value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("verdict text must be nonblank")
        return value.strip()


class EvidenceVerificationBatch(BaseModel):
    """Complete ordered evidence verdicts for one candidate batch."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    verdicts: list[EvidenceVerificationVerdict] = Field(min_length=1, max_length=MAX_QUESTIONS)


class AssessmentEvidenceVerifier:
    """Run one independent structured evidence-verification call per candidate batch."""

    def __init__(self, model: Any | None = None) -> None:
        self._model = model
        self._model_lock = RLock()

    def verify(
        self,
        request: GenerateQuestionsRequest,
        questions: Sequence[GeneratedQuestion],
        catalog: EvidenceExcerptCatalog,
    ) -> tuple[EvidenceVerificationVerdict, ...]:
        """Return a complete verdict tuple or fail closed without hidden retries."""

        if not questions:
            raise AssessmentVerificationError("at least one candidate question is required")
        messages = self._build_messages(request, questions, catalog)
        structured_model = self._structured_model(self._resolve_model())
        try:
            raw_output = structured_model.invoke(messages)
            batch = self._coerce_batch(raw_output)
        except AssessmentVerificationError:
            raise
        except Exception as exc:
            raise AssessmentVerificationError("assessment quality verification failed") from exc

        expected_indices = set(range(len(questions)))
        actual_indices = {verdict.question_index for verdict in batch.verdicts}
        if actual_indices != expected_indices or len(batch.verdicts) != len(questions):
            raise AssessmentVerificationError("assessment verifier returned incomplete question coverage")
        verdicts = tuple(sorted(batch.verdicts, key=lambda verdict: verdict.question_index))
        return verdicts

    def _resolve_model(self) -> Any:
        """Create the configured assessment model only when verification is needed."""

        if self._model is not None:
            return self._model
        with self._model_lock:
            if self._model is not None:
                return self._model
            try:
                from ds_course_agent.assessment.model_factory import get_assessment_verifier_model

                self._model = get_assessment_verifier_model()
            except Exception as exc:
                raise AssessmentVerificationError("assessment verifier model is unavailable") from exc
            if self._model is None:
                raise AssessmentVerificationError("assessment verifier model factory returned no model")
        return self._model

    @staticmethod
    def _structured_model(model: Any) -> Any:
        factory = getattr(model, "with_structured_output", None)
        if not callable(factory):
            raise AssessmentVerificationError("assessment verifier model does not support structured output")
        try:
            structured_model = factory(EvidenceVerificationBatch, method="json_schema")
        except Exception as exc:
            raise AssessmentVerificationError("assessment verifier cannot configure structured output") from exc
        if not callable(getattr(structured_model, "invoke", None)):
            raise AssessmentVerificationError("structured assessment verifier does not provide invoke()")
        return structured_model

    @staticmethod
    def _coerce_batch(raw_output: Any) -> EvidenceVerificationBatch:
        if isinstance(raw_output, EvidenceVerificationBatch):
            return raw_output
        if isinstance(raw_output, Mapping):
            try:
                return EvidenceVerificationBatch.model_validate(dict(raw_output))
            except ValidationError as exc:
                raise AssessmentVerificationError("assessment verifier returned invalid structured output") from exc
        raise AssessmentVerificationError("structured assessment verification output is not a verdict payload")

    @staticmethod
    def _build_messages(
        request: GenerateQuestionsRequest,
        questions: Sequence[GeneratedQuestion],
        catalog: EvidenceExcerptCatalog,
    ) -> list[Any]:
        from langchain_core.messages import HumanMessage, SystemMessage

        evidence_blocks = []
        for source in catalog.sources:
            source_excerpts = "\n".join(
                f"[{excerpt.id}] {excerpt.text}" for excerpt in catalog.excerpts if excerpt.source_id == source.id
            )
            evidence_blocks.append(
                f"[source_id={source.id}]\n来源：{source.source or '未提供'}\n"
                f"页码：{source.page or '未提供'}\n{source_excerpts}"
            )
        evidence_text = "\n\n".join(evidence_blocks)
        question_blocks = []
        for index, question in enumerate(questions):
            options = "\n".join(f"{option.id}. {option.text}" for option in question.options)
            question_blocks.append(f"[question_index={index}]\n题干：{question.stem}\n选项：\n{options}")
        questions_text = "\n\n".join(question_blocks)
        user_prompt = (
            f"目标知识点：{request.target_kc_id}\n难度：{request.difficulty.value}\n\n"
            f"教材证据：\n{evidence_text}\n\n候选题：\n{questions_text}"
        )
        if len(user_prompt) > MAX_VERIFIER_PROMPT_CHARS:
            raise AssessmentVerificationError("assessment verifier prompt exceeds its bounded context")
        return [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=user_prompt)]


__all__ = [
    "AssessmentVerificationError",
    "AssessmentEvidenceVerifier",
    "EvidenceVerificationBatch",
    "EvidenceVerificationVerdict",
    "EvidenceExcerpt",
    "EvidenceExcerptCatalog",
    "OptionEvidence",
]
