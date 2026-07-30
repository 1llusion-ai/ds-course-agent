from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from ds_course_agent.rag.query_pipeline.models import RouteIntent
from ds_course_agent.rag.query_pipeline.semantic_router import (
    LearningRouteOutput,
    LearningSemanticRouter,
)
from ds_course_agent.shared import llm as llm_module
from ds_course_agent.shared.config.schema import Settings


@dataclass
class _Runnable:
    response: Any = None
    error: Exception | None = None
    messages: list[Any] | None = None

    def invoke(self, messages: list[Any]) -> Any:
        self.messages = messages
        if self.error is not None:
            raise self.error
        return self.response


class _StructuredModel:
    def __init__(self, response: Any = None, *, error: Exception | None = None) -> None:
        self.runnable = _Runnable(response=response, error=error)
        self.schema = None
        self.structured_kwargs: dict[str, Any] = {}
        self.direct_invoke_called = False

    def with_structured_output(self, schema, **kwargs):
        self.schema = schema
        self.structured_kwargs = kwargs
        return self.runnable

    def invoke(self, messages):
        self.direct_invoke_called = True
        raise AssertionError("structured output path should be used")


class _PlainJsonModel:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.messages: list[Any] | None = None

    def with_structured_output(self, schema, **kwargs):
        raise NotImplementedError

    def invoke(self, messages):
        self.messages = messages
        return self.response


def test_semantic_router_returns_valid_structured_output():
    model = _StructuredModel(
        {
            "intent": "comparison",
            "confidence": 0.93,
            "needs_clarification": False,
        }
    )

    result = LearningSemanticRouter(model=model).route("比较逻辑回归和 SVM")

    assert result == LearningRouteOutput(
        intent=RouteIntent.COMPARISON,
        confidence=0.93,
        needs_clarification=False,
    )
    assert model.schema is LearningRouteOutput
    assert model.structured_kwargs == {"method": "json_schema"}
    assert model.direct_invoke_called is False


def test_semantic_router_parses_valid_json_when_structured_output_is_unavailable():
    model = _PlainJsonModel(
        AIMessage(content=('```json\n{"intent":"code_explanation","confidence":0.88,"needs_clarification":false}\n```'))
    )

    result = LearningSemanticRouter(model=model).route("解释这段代码")

    assert result.intent is RouteIntent.CODE_EXPLANATION
    assert result.confidence == 0.88
    assert result.needs_clarification is False


@pytest.mark.parametrize(
    "invalid_output",
    [
        {
            "intent": "current_datetime",
            "confidence": 0.9,
            "needs_clarification": False,
        },
        {
            "intent": "concept_qa",
            "confidence": 1.2,
            "needs_clarification": False,
        },
        {
            "intent": "concept_qa",
            "confidence": 0.9,
            "needs_clarification": False,
            "execution_mode": "grounded_generation",
        },
    ],
)
def test_semantic_router_rejects_invalid_or_non_learning_output(invalid_output):
    result = LearningSemanticRouter(model=_StructuredModel(invalid_output)).route("测试问题")

    assert result.intent is RouteIntent.NEEDS_CLARIFICATION
    assert result.confidence == 0.0
    assert result.needs_clarification is True


@pytest.mark.parametrize("error", [TimeoutError("timed out"), RuntimeError("provider failed")])
def test_semantic_router_fails_closed_on_timeout_or_model_error(error):
    model = _StructuredModel(error=error)

    result = LearningSemanticRouter(model=model).route("这个怎么理解？")

    assert result.intent is RouteIntent.NEEDS_CLARIFICATION
    assert result.confidence == 0.0
    assert result.needs_clarification is True
    assert model.direct_invoke_called is False


def test_semantic_router_sends_current_query_with_compact_recent_context():
    model = _StructuredModel(
        {
            "intent": "follow_up",
            "confidence": 0.91,
            "needs_clarification": False,
        }
    )
    recent_context = f"old-marker {'旧内容' * 80} latest-marker"

    result = LearningSemanticRouter(model=model, recent_context_max_chars=60).route(
        "那它为什么会这样？",
        recent_context,
    )

    assert result.intent is RouteIntent.FOLLOW_UP
    assert model.runnable.messages is not None
    human_prompt = model.runnable.messages[-1].content
    compact_context = human_prompt.split("最近上下文：\n", maxsplit=1)[1]
    assert "那它为什么会这样？" in human_prompt
    assert compact_context.startswith("…")
    assert len(compact_context) == 60
    assert "latest-marker" in compact_context
    assert "old-marker" not in compact_context


def test_router_settings_are_typed_and_bounded():
    settings = Settings(
        ROUTER_MODEL_NAME="router-model",
        ROUTER_MAX_TOKENS=96,
        ROUTER_TIMEOUT_SECONDS=2.5,
        ROUTER_MAX_RETRIES=1,
        ROUTER_RECENT_CONTEXT_MAX_CHARS=640,
    )

    assert settings.ROUTER_MODEL_NAME == "router-model"
    assert settings.ROUTER_MAX_TOKENS == 96
    assert settings.ROUTER_TIMEOUT_SECONDS == 2.5
    assert settings.ROUTER_MAX_RETRIES == 1
    assert settings.ROUTER_RECENT_CONTEXT_MAX_CHARS == 640

    with pytest.raises(ValidationError):
        Settings(ROUTER_MAX_TOKENS=0)


@pytest.mark.parametrize(
    ("configured_name", "expected_name"),
    [
        ("", "current-chat-model"),
        ("dedicated-router-model", "dedicated-router-model"),
    ],
)
def test_get_router_model_uses_dedicated_remote_budget(
    monkeypatch,
    configured_name,
    expected_name,
):
    captured: dict[str, Any] = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    import langchain_openai

    monkeypatch.setattr(langchain_openai, "ChatOpenAI", FakeChatOpenAI)
    monkeypatch.setattr(llm_module.config, "USE_REMOTE_LLM", True)
    monkeypatch.setattr(llm_module.config, "ROUTER_MODEL_NAME", configured_name)
    monkeypatch.setattr(llm_module.config, "REMOTE_MODEL_NAME", "current-chat-model")
    monkeypatch.setattr(llm_module.config, "ROUTER_MAX_TOKENS", 96)
    monkeypatch.setattr(llm_module.config, "ROUTER_TIMEOUT_SECONDS", 2.0)
    monkeypatch.setattr(llm_module.config, "ROUTER_MAX_RETRIES", 0)

    llm_module.get_router_model()

    assert captured["model"] == expected_name
    assert captured["temperature"] == 0.0
    assert captured["max_completion_tokens"] == 96
    assert captured["timeout"] == 2.0
    assert captured["max_retries"] == 0
    assert captured["streaming"] is False
