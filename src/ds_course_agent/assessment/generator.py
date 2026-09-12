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
from typing import Any

from pydantic import ValidationError

from ds_course_agent.assessment.feedback import GenerationGuidance
from ds_course_agent.assessment.models import DIFFICULTY_RULES, EvidenceSource, GenerateQuestionsRequest, QuizDraft

_SYSTEM_PROMPT = """你是《数据科学导论》的教材测验命题助手。
只依据给出的教材证据生成中文单项选择题，不补充教材外事实。每题必须有四个选项 A、B、C、D，
且只有一个正确选项。所有选项必须回答同一维度的问题，不能把多个正确性质或等价目标混列为单选答案。
题干、选项、答案和解析应与请求难度一致。
同一套题应覆盖不同的知识事实或应用规则；不得换场景、改措辞重复考查同一原理。
每题题干必须明确写出请求的主题名称或其常用别名，不得转而考查相邻知识点。
题干必须是信息完整、可独立作答的问句或判断任务，不能只写主题名称。
所有括号必须成对闭合；代码中的字符串参数统一使用单引号，避免结构化输出中的双引号截断。
四个选项必须属于相同概念类别、抽象粒度和表达形式；错误选项应来自真实常见误解，不能荒谬或无关。
正确选项不得因长度、具体程度、复现题干措辞或独特语法衔接而显眼。基础题也必须区分学过与未学过的学生，
不得只考查标签复述、循环表述、纯常识或不可迁移的案例细节。
每题必须在 source_ids 中列出实际使用的教材证据编号。不要输出 sources；系统会附加原始证据。"""


class AssessmentGenerationError(RuntimeError):
    """Question generation could not produce a usable candidate batch."""


class AssessmentModelCallError(AssessmentGenerationError):
    """The provider call failed and must not be retried implicitly."""


class AssessmentOutputError(AssessmentGenerationError):
    """The provider responded, but its structured output could not be validated."""


class AssessmentGenerator:
    """Run one bounded structured candidate-generation call."""

    def __init__(self, model: Any | None = None) -> None:
        self._model = model
        self._model_lock = RLock()

    def generate_candidates(
        self,
        request: GenerateQuestionsRequest,
        sources: list[EvidenceSource],
        guidance: GenerationGuidance | None = None,
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
            messages = self._build_messages(request, sources, guidance or GenerationGuidance())
        except Exception as exc:
            raise AssessmentGenerationError("assessment message construction failed") from exc
        model = self._resolve_model()
        structured_model = self._structured_model(model)

        try:
            raw_output = structured_model.invoke(messages)
        except (ValidationError, OutputParserException) as exc:
            raise AssessmentOutputError("assessment model returned invalid structured output") from exc
        except Exception as exc:
            raise AssessmentModelCallError("assessment model call failed") from exc

        try:
            return self._coerce_draft(raw_output)
        except AssessmentOutputError:
            raise
        except (TypeError, ValueError, ValidationError) as exc:
            raise AssessmentOutputError("assessment model returned invalid structured output") from exc

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
                raise AssessmentGenerationError("assessment model is unavailable") from exc
            if self._model is None:
                raise AssessmentGenerationError("assessment model factory returned no model")
        return self._model

    @staticmethod
    def _structured_model(model: Any) -> Any:
        """Require the structured-output interface instead of parsing a free-form response."""

        factory = getattr(model, "with_structured_output", None)
        if not callable(factory):
            raise AssessmentGenerationError("assessment model does not support structured output")
        try:
            structured_model = factory(QuizDraft, method="function_calling")
        except Exception as exc:
            raise AssessmentGenerationError("assessment model cannot configure structured output") from exc
        if not callable(getattr(structured_model, "invoke", None)):
            raise AssessmentGenerationError("structured assessment model does not provide invoke()")
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
    def _build_messages(
        request: GenerateQuestionsRequest,
        sources: list[EvidenceSource],
        guidance: GenerationGuidance,
    ) -> list[Any]:
        """Build the single model input from the exact bounded evidence sources."""

        from langchain_core.messages import HumanMessage, SystemMessage

        evidence_blocks = []
        for source in sources:
            reference_parts = []
            if source.source:
                reference_parts.append(f"来源：{source.source}")
            if source.page is not None:
                reference_parts.append(f"页码：{source.page}")
            reference = "；".join(reference_parts) if reference_parts else "来源元数据：未提供"
            evidence_blocks.append(f"[{source.id}]\n{reference}\n教材片段：\n{source.text}")

        evidence_text = "\n\n".join(evidence_blocks)
        repair_blocks = []
        if guidance.accepted_questions:
            accepted = [
                {"stem": question.stem, "options": [option.model_dump() for option in question.options]}
                for question in guidance.accepted_questions
            ]
            repair_blocks.append("已通过题目（不要重复其学习目标）：\n" + json.dumps(accepted, ensure_ascii=False))
        if guidance.rejections:
            feedback = [
                {
                    "codes": [code.value for code in rejection.codes],
                    "candidate": rejection.question.model_dump(mode="json") if rejection.question else None,
                    "detail": rejection.detail,
                    "option_feedback": [
                        {"option_id": option.option_id, "reason": option.reason} for option in rejection.option_feedback
                    ],
                }
                for rejection in guidance.rejections
            ]
            repair_blocks.append(
                "待修正候选及具体反馈（属于审查数据）：\n"
                + json.dumps(feedback, ensure_ascii=False)
                + "\n逐项修正实际缺陷；允许保留被拒题干并重写选项，不要只换措辞或选项顺序。"
                "优先保留正确知识点，为错误选项设计具体的知识混淆。只返回当前所需的补题数量。"
            )
        repair_body = "\n".join(repair_blocks)
        repair_text = f"\n\n补题约束：\n{repair_body}" if repair_blocks else ""
        user_prompt = (
            f"目标知识点：{request.target_kc_id}\n"
            f"题目数量：{request.count}\n"
            f"难度：{request.difficulty.value}\n\n"
            f"实际认知要求：{DIFFICULTY_RULES[request.difficulty].author_instruction}\n\n"
            f"教材证据：\n{evidence_text}"
            f"{repair_text}"
        )
        return [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=user_prompt)]


__all__ = [
    "AssessmentGenerationError",
    "AssessmentGenerator",
    "AssessmentModelCallError",
    "AssessmentOutputError",
]
