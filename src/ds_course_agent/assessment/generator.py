"""Generate validated, textbook-grounded single-choice quiz drafts.

The one-shot ``with_structured_output`` shape is conceptually adapted from
``ai-mini-quiz-generator``'s ``utils.py`` (Melek Nur, MIT, upstream commit
``86db2ffd80d99d8db41b3b4f85d00129a23f80be``). No upstream code is vendored.

Upstream MIT notice:

Copyright 2026 Melek Nur

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the “Software”), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
of the Software, and to permit persons to whom the Software is furnished to do
so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from threading import RLock
from typing import Any, Protocol

from pydantic import ValidationError

from ds_course_agent.assessment.feedback import (
    AssessmentFailureKind,
    QuestionRepairBatch,
    QuestionRepairRequest,
    classify_provider_error,
)
from ds_course_agent.assessment.formulas import analyze_formula_quality
from ds_course_agent.assessment.generation_constraints import AssessmentExposureConstraint
from ds_course_agent.assessment.models import (
    DIFFICULTY_RULES,
    Difficulty,
    EvidenceSource,
    FormulaQuality,
    GenerateQuestionsRequest,
    QuizDraft,
)
from ds_course_agent.assessment.task_context import AssessmentTaskContext

MAX_AUTHOR_PROMPT_CHARS = 64_000
MAX_EXPOSURE_EXAMPLE_CHARS = 4_000

_REPAIR_ACTIONS = {
    "target_coverage_gap": "改考拒绝信息列出的缺失成员，并让正确答案有相应教材片段支持；仅在题干罗列全名不能补足覆盖。",
    "recent_item_exposure": "更换为当前学生近期和活跃评估未见的题目内容；不能仅重排选项或改解析。",
    "answer_leakage": "消除可凭长度、措辞、语法或题干复现猜中的线索，同时保持四个选项同类同粒度。",
    "answer_ambiguity": "重新审查四个选项，改写或删除任何也能回答题干的选项，确保只有一个选项成立。",
    "multiple_correct_answers": "缩小题干条件或重写选项，使教材证据只支持一个选项；不能把多个成立选项保留为单选题。",
    "answer_not_supported": "重新选择教材明确支持的正确事实；不能用审查反馈或教材外知识补足证据。",
    "uncertain_evidence": "只使用教材证据中明确、确定的结论；证据不足时更换为可被证据直接支持的题目。",
    "source_mismatch": "让正确答案实际由其 source_ids 指向的教材证据支持，并只引用实际使用的 source_ids。",
    "unknown_source": "只填写当前教材证据中提供的 source_ids，不创造或猜测编号。",
    "unknown_evidence_reference": "不要在题目内容中编造证据编号；source_ids 只能来自当前教材证据。",
    "formula_mismatch": "逐字符核对教材中的公式、符号和数值；无法从证据准确复现时改用非公式题。",
    "off_topic": "题干必须明确考查目标知识点或其常用别名，不要转向相邻概念。",
    "difficulty_mismatch": "按请求难度重新设计认知要求，不要只给题目贴标签或改 difficulty 字段。",
    "cognitive_operation_mismatch": "按该槽位的 observable_tasks 重建作答任务；定义识别 recall 不能满足关系比较 interpretation。",
    "duplicate_stem": "更换为未出现过的题干和学习目标，不要只替换同义词。",
    "semantic_duplicate": "考查不同的教材事实或应用规则；不能让掌握已通过题目就能机械复述答案。",
    "implausible_distractors": "把错误选项改为针对真实常见误解的同类候选，避免荒谬、无关或不同抽象层级。",
    "low_pedagogical_value": "增加可迁移的概念区分、关系解释或应用判断，避免纯常识、标签复述和不可迁移细节。",
    "question_count_shortfall": "补齐所有缺失题目数量，每题都必须完整包含四个选项、唯一答案、解析和 source_ids。",
    "invalid_structured_output": "重新输出符合 QuizDraft 结构的完整题目，不输出额外字段或自由文本。",
}

_SYSTEM_PROMPT = """你是当前课程的教材测验命题助手。依据教材证据和槽位任务生成中文单项选择题。
每题四个选项 A、B、C、D，且只有一个正确答案；选项须同维度、同粒度，干扰项体现合理误解。
题干须完整、可独立作答，不能只写主题名称；正确选项不得因长度、措辞复现或语法而显眼。
考查目标知识点或声明成员；整套题覆盖全部成员，考查不同事实或规则，不靠换场景重复考同一原理。
实际作答任务须符合槽位认知操作和难度，不能靠题目标签或加长情境提高难度。
学习记录仅用于决定练习重点、提示程度和干扰项，不是教材事实；优先检验已记录的错误，
不推断未观察到的误解，不把提及次数当作掌握程度。答案和解析只依据下方教材，不补充教材外结论。
所有括号须闭合；代码字符串参数统一使用单引号。source_ids 列出实际使用的证据编号；不输出 sources。"""


class AssessmentGenerationError(RuntimeError):
    """Question generation could not produce a usable candidate batch."""

    failure_kind = AssessmentFailureKind.QUESTION_SLOT_FAILURE

    def __init__(
        self,
        message: str,
        *,
        slot_failures=(),
        progress=None,
        failure_kind: AssessmentFailureKind | None = None,
    ) -> None:
        super().__init__(message)
        self.slot_failures = tuple(slot_failures)
        self.progress = progress
        if failure_kind is not None:
            self.failure_kind = failure_kind


class AssessmentModelCallError(AssessmentGenerationError):
    """The provider call failed and must not be retried implicitly."""

    failure_kind = AssessmentFailureKind.PROVIDER_TRANSIENT_FAILURE


class AssessmentOutputError(AssessmentGenerationError):
    """The provider responded, but its structured output could not be validated."""

    failure_kind = AssessmentFailureKind.QUESTION_SLOT_FAILURE


class AssessmentEditorModelCallError(AssessmentGenerationError):
    """The large-model item editor failed at the provider boundary."""

    failure_kind = AssessmentFailureKind.PROVIDER_TRANSIENT_FAILURE


class AssessmentEditorOutputError(AssessmentGenerationError):
    """The item editor returned output that cannot fill its assigned slot."""

    failure_kind = AssessmentFailureKind.QUESTION_SLOT_FAILURE


class AssessmentItemEditor(Protocol):
    """Typed boundary for repairing a batch of rejected question slots."""

    def revise_items(self, request: QuestionRepairRequest) -> QuestionRepairBatch:
        """Return slot-addressed revisions using one server-owned evidence snapshot."""


class AssessmentGenerator:
    """Batch draft candidates and revise rejected slots in one editor call."""

    def __init__(self, model: Any | None = None, *, editor_model: Any | None = None) -> None:
        self._model = model
        self._editor_model = editor_model
        self._model_lock = RLock()
        self._editor_model_lock = RLock()

    def generate_candidates(
        self,
        context: AssessmentTaskContext,
        sources: list[EvidenceSource],
        *,
        exposure: AssessmentExposureConstraint = AssessmentExposureConstraint(),
    ) -> QuizDraft:
        """Generate a structurally parsed candidate batch without hidden retries.

        Cross-question and target-specific acceptance is owned by the service so
        valid questions can survive a bounded repair pass.
        """
        from langchain_core.exceptions import OutputParserException

        if not sources:
            raise AssessmentGenerationError("at least one evidence source is required")
        if len({source.id for source in sources}) != len(sources):
            raise AssessmentGenerationError("evidence source ids must be unique")

        try:
            messages = self._build_messages(context, sources, exposure=exposure)
        except Exception as exc:
            raise AssessmentGenerationError("assessment message construction failed") from exc
        model = self._resolve_author_model(context.request, sources)
        structured_model = self._structured_model(model, QuizDraft)

        try:
            raw_output = structured_model.invoke(messages)
        except (ValidationError, OutputParserException) as exc:
            raise AssessmentOutputError("assessment model returned invalid structured output") from exc
        except Exception as exc:
            raise AssessmentModelCallError(
                "assessment model call failed", failure_kind=classify_provider_error(exc)
            ) from exc

        try:
            return self._coerce_draft(raw_output)
        except AssessmentOutputError:
            raise
        except (TypeError, ValueError, ValidationError) as exc:
            raise AssessmentOutputError("assessment model returned invalid structured output") from exc

    def revise_items(self, request: QuestionRepairRequest) -> QuestionRepairBatch:
        """Use one editor call to repair all requested slots without regenerating accepted items."""

        if not isinstance(request, QuestionRepairRequest):
            raise TypeError("assessment item editor requires QuestionRepairRequest")
        try:
            messages = self._build_revision_messages(request)
        except Exception as exc:
            raise AssessmentGenerationError("assessment repair message construction failed") from exc
        model = self._resolve_editor_model()
        structured_model = self._structured_model(model, QuestionRepairBatch)

        from langchain_core.exceptions import OutputParserException

        try:
            raw_output = structured_model.invoke(messages)
        except (ValidationError, OutputParserException) as exc:
            raise AssessmentEditorOutputError("assessment editor returned invalid structured output") from exc
        except Exception as exc:
            raise AssessmentEditorModelCallError(
                "assessment editor model call failed", failure_kind=classify_provider_error(exc)
            ) from exc

        try:
            return self._coerce_repair_batch(raw_output)
        except (TypeError, ValueError, ValidationError) as exc:
            raise AssessmentEditorOutputError("assessment editor returned invalid structured output") from exc

    def _resolve_model(self) -> Any:
        """Create the configured model only when generation is actually requested."""

        if self._model is not None:
            return self._model

        with self._model_lock:
            if self._model is not None:
                return self._model
            try:
                from ds_course_agent.assessment.model_factory import get_assessment_generator_model

                self._model = get_assessment_generator_model()
            except Exception as exc:
                raise AssessmentModelCallError(
                    "assessment model is unavailable", failure_kind=classify_provider_error(exc)
                ) from exc
            if self._model is None:
                raise AssessmentModelCallError("assessment model factory returned no model")
        return self._model

    def _resolve_editor_model(self) -> Any:
        """Create the larger repair model lazily when item repair is needed."""

        if self._editor_model is not None:
            return self._editor_model
        with self._editor_model_lock:
            if self._editor_model is not None:
                return self._editor_model
            try:
                from ds_course_agent.assessment.model_factory import get_assessment_editor_model

                self._editor_model = get_assessment_editor_model()
            except Exception as exc:
                raise AssessmentEditorModelCallError(
                    "assessment editor model is unavailable", failure_kind=classify_provider_error(exc)
                ) from exc
            if self._editor_model is None:
                raise AssessmentEditorModelCallError("assessment editor model factory returned no model")
        return self._editor_model

    def _resolve_author_model(self, request: GenerateQuestionsRequest, sources: list[EvidenceSource]) -> Any:
        if request.difficulty is Difficulty.ADVANCED or any(
            analyze_formula_quality(source.text)[1] is FormulaQuality.VALID for source in sources
        ):
            return self._resolve_editor_model()
        return self._resolve_model()

    @staticmethod
    def _structured_model(model: Any, schema: Any) -> Any:
        """Require the structured-output interface instead of parsing a free-form response."""

        factory = getattr(model, "with_structured_output", None)
        if not callable(factory):
            error = RuntimeError("assessment model does not support structured output")
            raise AssessmentModelCallError(
                "assessment model does not support structured output",
                failure_kind=classify_provider_error(error),
            ) from error
        try:
            structured_model = factory(schema, method="function_calling")
        except Exception as exc:
            raise AssessmentModelCallError(
                "assessment model cannot configure structured output",
                failure_kind=classify_provider_error(exc),
            ) from exc
        if not callable(getattr(structured_model, "invoke", None)):
            error = RuntimeError("structured assessment model does not provide invoke()")
            raise AssessmentModelCallError(
                "structured assessment model does not provide invoke()",
                failure_kind=classify_provider_error(error),
            ) from error
        return structured_model

    @staticmethod
    def _coerce_draft(raw_output: Any) -> QuizDraft:
        """Normalize supported structured-output return values into the local model."""

        if isinstance(raw_output, QuizDraft):
            return raw_output
        if isinstance(raw_output, Mapping):
            return QuizDraft.model_validate(dict(raw_output))
        raise TypeError("structured assessment output is not a quiz payload")

    @staticmethod
    def _coerce_repair_batch(raw_output: Any) -> QuestionRepairBatch:
        """Normalize one structured editor response into the slot-addressed batch type."""

        if isinstance(raw_output, QuestionRepairBatch):
            return raw_output
        if isinstance(raw_output, Mapping):
            return QuestionRepairBatch.model_validate(dict(raw_output))
        raise TypeError("structured assessment editor output is not a repair batch payload")

    @staticmethod
    def _build_messages(
        context: AssessmentTaskContext,
        sources: list[EvidenceSource],
        *,
        exposure: AssessmentExposureConstraint = AssessmentExposureConstraint(),
    ) -> list[Any]:
        """Build the single model input from the exact bounded evidence sources."""

        from langchain_core.messages import HumanMessage, SystemMessage

        request = context.request
        user_prompt = (
            f"目标知识点：{context.target_text()}\n"
            f"题目数量：{request.count}\n"
            f"难度：{request.difficulty.value}\n\n"
            f"实际认知要求：{DIFFICULTY_RULES[request.difficulty].author_instruction}\n\n"
            "共享教学要求（questions 必须按 slot_index 顺序返回，每题遵守对应槽位任务）：\n"
            f"{context.author_text()}\n\n"
            f"学生画像与相关学习记录（仅当前知识点）：\n{context.learner_text()}\n\n"
            f"教材证据：\n{AssessmentGenerator._evidence_text(sources)}"
        )
        user_prompt = AssessmentGenerator._with_exposure(user_prompt, exposure, _SYSTEM_PROMPT)
        return [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=user_prompt)]

    @staticmethod
    def _build_revision_messages(request: QuestionRepairRequest) -> list[Any]:
        """Build one batch repair prompt with typed feedback and one trusted evidence snapshot."""

        from langchain_core.messages import HumanMessage, SystemMessage

        context = request.context
        slots = []
        for slot in request.slots:
            rejection = slot.rejection
            candidate = None
            if rejection.question is not None:
                candidate = {
                    "stem": rejection.question.stem,
                    "options": [option.model_dump() for option in rejection.question.options],
                    "difficulty": rejection.question.difficulty.value,
                }
            slots.append(
                {
                    "slot_id": slot.slot_id,
                    "slot_index": slot.slot_index,
                    "rejection_codes": [code.value for code in rejection.codes],
                    "repair_actions": [
                        _REPAIR_ACTIONS.get(code.value, "修复该拒绝码对应的实际缺陷，并重新满足全部硬约束。")
                        for code in rejection.codes
                    ],
                    "candidate": candidate,
                    "detail": rejection.detail,
                    "option_feedback": [
                        {"option_id": item.option_id, "reason": item.reason} for item in rejection.option_feedback
                    ],
                }
            )
        accepted = [
            {"stem": question.stem, "options": [option.model_dump() for option in question.options]}
            for question in request.accepted_questions
        ]
        user_prompt = (
            "这是一次批量槽位修订。对每个输入 slot_id 至少返回一个 revisions 项，"
            "slot_id 必须逐字稳定匹配；不要返回未请求的槽位，也不要遗漏可修订槽位。\n"
            f"目标知识点：{context.target_text()}\n"
            f"难度：{context.request.difficulty.value}\n"
            f"实际认知要求：{DIFFICULTY_RULES[context.request.difficulty].author_instruction}\n"
            f"共享教学要求：{context.author_text()}\n\n"
            f"学生画像与相关学习记录（仅当前知识点）：\n{context.learner_text()}\n\n"
            "拒绝信息（这是审查反馈，不是教材事实；必须先重新依据下方教材证据判断）：\n"
            f"{json.dumps(slots, ensure_ascii=False)}\n\n"
            "已通过题目（只用于避免重复学习目标）：\n"
            f"{json.dumps(accepted, ensure_ascii=False) if accepted else '无'}\n\n"
            "服务器拥有的教材证据：\n"
            f"{AssessmentGenerator._evidence_text(request.evidence)}\n\n"
            "修订后的题目必须再次满足四个选项、唯一答案、目标主题、请求难度和教材证据约束；"
            "source_ids 只能填写上方证据的编号，不能创造编号。不要把拒绝信息中的推断当作教材结论。"
        )
        user_prompt = AssessmentGenerator._with_exposure(user_prompt, request.exposure, _SYSTEM_PROMPT)
        return [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=user_prompt)]

    @staticmethod
    def _with_exposure(user_prompt: str, exposure: AssessmentExposureConstraint, system_prompt: str) -> str:
        """Budget optional avoid examples within the actual full author/editor cap."""
        remaining = MAX_AUTHOR_PROMPT_CHARS - len(user_prompt) - len(system_prompt) - 2
        if remaining < 0:
            raise AssessmentGenerationError("assessment author/editor prompt exceeds its character budget")
        header = "当前学生活跃或近期题目（不得重新生成，重排选项也算重复）：\n"
        budget = min(MAX_EXPOSURE_EXAMPLE_CHARS, remaining)
        examples = []
        for question in exposure.excluded_questions:
            example = {"stem": question.stem, "options": [option.text for option in question.options]}
            if len(header) + len(json.dumps([*examples, example], ensure_ascii=False)) > budget:
                continue
            examples.append(example)
        return user_prompt + ("\n\n" + header + json.dumps(examples, ensure_ascii=False) if examples else "")

    @staticmethod
    def _evidence_text(sources: list[EvidenceSource] | tuple[EvidenceSource, ...]) -> str:
        evidence_blocks = []
        for source in sources:
            reference_parts = []
            if source.source:
                reference_parts.append(f"来源：{source.source}")
            if source.page is not None:
                reference_parts.append(f"页码：{source.page}")
            reference = "；".join(reference_parts) if reference_parts else "来源元数据：未提供"
            evidence_blocks.append(f"[{source.id}]\n{reference}\n教材片段：\n{source.text}")
        return "\n\n".join(evidence_blocks)


__all__ = [
    "AssessmentEditorModelCallError",
    "AssessmentEditorOutputError",
    "AssessmentGenerationError",
    "AssessmentItemEditor",
    "AssessmentGenerator",
    "AssessmentModelCallError",
    "AssessmentOutputError",
]
