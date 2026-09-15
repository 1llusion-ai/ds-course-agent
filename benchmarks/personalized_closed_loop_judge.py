"""Semantic Judge for personalized closed-loop traces."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

import ds_course_agent.shared.config as config


def _create_model(model_name: str) -> Any:
    """Create a non-streaming OpenAI-compatible judge model from project config."""

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=model_name,
        api_key=config.API_KEY,
        base_url=config.BASE_URL,
        temperature=0.0,
        max_completion_tokens=config.CHAT_MAX_TOKENS,
        timeout=config.CHAT_TIMEOUT_SECONDS,
        max_retries=0,
        streaming=False,
    )


class JudgeCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    passed: bool
    evidence: str = Field(min_length=1, max_length=1_000)


class JudgeVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    kc_correct: JudgeCriterion
    profile_faithful: JudgeCriterion
    student_isolation: JudgeCriterion
    personalization_used: JudgeCriterion
    question_adapted: JudgeCriterion
    needs_human_review: bool
    review_reason: str = Field(default="", max_length=1_000)


JUDGE_PROMPT = """你是数据科学导论课程助教闭环评测 Judge。
只依据输入中的事实、允许证据、禁止证据和系统输出判断，不得补充未提供的学生历史。
三项硬门槛 kc_correct、profile_faithful、student_isolation 只要证据不足就判失败并要求人工复检。
每个 evidence 必须引用具体回答片段或结构化事实；不能写泛泛评价。
"""


class JudgeError(RuntimeError):
    """Judge failed to produce a trustworthy structured verdict."""


class PersonalizedClosedLoopJudge:
    """Invoke one independent structured model and preserve prompt provenance."""

    def __init__(self, *, model_name: str, reasoning_effort: str = "high", model: Any | None = None) -> None:
        self.model_name = model_name
        self.reasoning_effort = reasoning_effort
        self._model = model or _create_model(model_name)

    @property
    def prompt_sha256(self) -> str:
        return hashlib.sha256(JUDGE_PROMPT.encode("utf-8")).hexdigest()

    def judge(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Return a schema-valid verdict or a conservative human-review result."""

        try:
            structured = self._model.with_structured_output(JudgeVerdict, method="json_schema")
            result = structured.invoke(
                [
                    ("system", JUDGE_PROMPT),
                    ("user", json.dumps(payload, ensure_ascii=False, sort_keys=True)),
                ]
            )
            verdict = result if isinstance(result, JudgeVerdict) else JudgeVerdict.model_validate(result)
            return verdict.model_dump(mode="json")
        except Exception as exc:
            return JudgeVerdict(
                kc_correct=JudgeCriterion(passed=False, evidence="Judge 请求或结构化解析失败"),
                profile_faithful=JudgeCriterion(passed=False, evidence="Judge 请求或结构化解析失败"),
                student_isolation=JudgeCriterion(passed=False, evidence="Judge 请求或结构化解析失败"),
                personalization_used=JudgeCriterion(passed=False, evidence="Judge 请求或结构化解析失败"),
                question_adapted=JudgeCriterion(passed=False, evidence="Judge 请求或结构化解析失败"),
                needs_human_review=True,
                review_reason=f"judge_error:{type(exc).__name__}",
            ).model_dump(mode="json")


__all__ = ["JudgeCriterion", "JudgeVerdict", "PersonalizedClosedLoopJudge", "JudgeError", "JUDGE_PROMPT"]
