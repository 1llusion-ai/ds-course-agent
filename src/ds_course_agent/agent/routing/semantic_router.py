"""LLM-backed semantic classification for ambiguous learning queries."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field, field_validator

import ds_course_agent.shared.config as config
from ds_course_agent.agent.routing.models import RouteIntent
from ds_course_agent.shared.llm import get_router_model
from ds_course_agent.shared.messages import message_content_text

logger = logging.getLogger(__name__)

_LEARNING_INTENT_VALUES = (
    "concept_qa",
    "comparison",
    "follow_up",
    "code_example",
    "code_explanation",
    "code_review",
    "code_execution",
    "learning_path",
    "misconception_repair",
    "personalized_explanation",
    "open_learning",
    "not_learning",
    "needs_clarification",
)
ALLOWED_LEARNING_INTENTS = frozenset(RouteIntent(value) for value in _LEARNING_INTENT_VALUES)
_NEEDS_CLARIFICATION_INTENT = RouteIntent("needs_clarification")

_SYSTEM_PROMPT = """你是《数据科学导论》助教的学习意图分类器。
只根据当前问题和最近上下文选择一个意图，不回答问题。

可选意图：
- concept_qa：解释课程概念、原理、机制或一般课程问题
- comparison：比较两个或多个概念、方法或模型
- follow_up：依赖最近对话才能理解的追问
- code_example：要求编写或演示代码，但没有要求实际运行
- code_explanation：要求解释已有代码的含义或步骤
- code_review：要求检查、诊断、纠正或改进已有代码
- code_execution：明确要求运行代码并返回输出
- learning_path：要求安排学习、复习顺序或学习计划
- misconception_repair：用户表达了需要纠正的具体错误理解
- personalized_explanation：明确要求结合个人学习状态重新讲解
- open_learning：属于课程或数据科学学习，但不适合前述具体意图
- not_learning：请求不属于课程学习或数据科学学习
- needs_clarification：信息不足，无法可靠判断用户目标

confidence 必须在 0 到 1 之间。只有确实需要用户补充信息时，
needs_clarification 才为 true。严格按给定结构输出。"""


class LearningRouteOutput(BaseModel):
    """Validated semantic-router output with no execution or tool controls."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    intent: RouteIntent
    confidence: float = Field(ge=0.0, le=1.0)
    needs_clarification: bool

    @field_validator("intent")
    @classmethod
    def _validate_learning_intent(cls, value: RouteIntent) -> RouteIntent:
        if value not in ALLOWED_LEARNING_INTENTS:
            raise ValueError(f"{value.value!r} is not an allowed learning-router intent")
        return value


class LearningSemanticRouter:
    """Classify ambiguous learning candidates without granting execution rights."""

    def __init__(self, model: Any | None = None, *, recent_context_max_chars: int | None = None) -> None:
        self._model = model if model is not None else get_router_model()
        configured_limit = (
            config.ROUTER_RECENT_CONTEXT_MAX_CHARS if recent_context_max_chars is None else recent_context_max_chars
        )
        self._recent_context_max_chars = max(0, int(configured_limit))

    def route(self, query: str, recent_context: str = "") -> LearningRouteOutput:
        """Return a validated learning intent or a fail-closed clarification result."""

        messages = self._build_messages(query, recent_context)
        try:
            raw_output = self._invoke(messages)
            return self._validate_output(raw_output)
        except Exception as exc:
            logger.warning("Learning semantic router degraded to clarification after %s", type(exc).__name__)
            return self._clarification_output()

    def _invoke(self, messages: list[Any]) -> Any:
        structured_factory = getattr(self._model, "with_structured_output", None)
        if callable(structured_factory):
            try:
                structured_model = structured_factory(LearningRouteOutput, method="json_schema")
            except (AttributeError, NotImplementedError, TypeError):
                structured_model = None

            if structured_model is not None:
                structured_invoke = getattr(structured_model, "invoke", None)
                if callable(structured_invoke):
                    try:
                        return structured_invoke(messages)
                    except (AttributeError, NotImplementedError):
                        pass

        invoke = getattr(self._model, "invoke", None)
        if not callable(invoke):
            raise TypeError("router model does not provide invoke()")
        return invoke(messages)

    def _build_messages(self, query: str, recent_context: str) -> list[Any]:
        normalized_query = str(query or "").strip()
        compact_context = self._compact_recent_context(recent_context)
        context_section = compact_context if compact_context else "（无）"
        user_prompt = f"当前问题：\n{normalized_query}\n\n最近上下文：\n{context_section}"
        return [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]

    def _compact_recent_context(self, recent_context: str) -> str:
        compact = " ".join(str(recent_context or "").split())
        limit = self._recent_context_max_chars
        if not compact or limit == 0:
            return ""
        if len(compact) <= limit:
            return compact
        return f"…{compact[-(limit - 1) :]}" if limit > 1 else "…"

    @staticmethod
    def _validate_output(raw_output: Any) -> LearningRouteOutput:
        if isinstance(raw_output, LearningRouteOutput):
            return raw_output
        if isinstance(raw_output, BaseModel):
            payload = raw_output.model_dump()
            if {"intent", "confidence", "needs_clarification"} <= payload.keys():
                return LearningRouteOutput.model_validate(payload)
        if isinstance(raw_output, Mapping):
            return LearningRouteOutput.model_validate(dict(raw_output))

        content = message_content_text(raw_output).strip()
        if not content:
            raise ValueError("router model returned empty output")
        return LearningRouteOutput.model_validate_json(_strip_json_fence(content))

    @staticmethod
    def _clarification_output() -> LearningRouteOutput:
        return LearningRouteOutput(
            intent=_NEEDS_CLARIFICATION_INTENT,
            confidence=0.0,
            needs_clarification=True,
        )


def _strip_json_fence(content: str) -> str:
    """Remove one optional Markdown JSON fence while keeping parsing strict."""

    stripped = content.strip()
    if not stripped.startswith("```"):
        return stripped

    lines = stripped.splitlines()
    if len(lines) < 3 or not lines[-1].strip().startswith("```"):
        raise json.JSONDecodeError("unterminated JSON fence", stripped, 0)
    return "\n".join(lines[1:-1]).strip()


_semantic_router: LearningSemanticRouter | None = None


def get_learning_semantic_router() -> LearningSemanticRouter:
    """Return the process-local semantic router."""

    global _semantic_router
    if _semantic_router is None:
        _semantic_router = LearningSemanticRouter()
    return _semantic_router


__all__ = [
    "ALLOWED_LEARNING_INTENTS",
    "get_learning_semantic_router",
    "LearningRouteOutput",
    "LearningSemanticRouter",
]
