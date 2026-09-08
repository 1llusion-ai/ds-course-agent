"""Ownership contracts for the extracted model runtime."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from langchain_core.messages import AIMessage

from ds_course_agent.agent.service import AgentService
from ds_course_agent.runtime.model_runtime import ModelRuntime
from ds_course_agent.runtime.model_stream import iter_agent_stream_messages
from ds_course_agent.shared.query_trace import begin_query_trace, end_query_trace


def _runtime(model: Mock, fallback=None) -> ModelRuntime:
    return ModelRuntime(llm=model, tool_registry=Mock(), system_prompt="", fallback=fallback)


def test_agent_service_does_not_retain_model_runtime_private_methods() -> None:
    """Model invocation and stream decoding must have one implementation owner."""

    removed_methods = (
        "_warn_context_budget",
        "_govern_context_budget",
        "_classify_llm_error",
        "_invoke_messages_with_retry",
        "_invoke_direct_messages_with_retry",
        "_stream_chat_with_retry",
        "_stream_direct_messages_with_retry",
        "_stream_chat_messages",
        "_create_agent",
        "_agent_for_tools",
        "_check_ollama_connection",
        "_yield_text_chunks",
    )

    assert all(not hasattr(AgentService, name) for name in removed_methods)
    assert callable(ModelRuntime.chat)
    assert callable(ModelRuntime.agent_for_tools)
    assert callable(iter_agent_stream_messages)
    assert callable(ModelRuntime._invoke_with_retry)


def test_retryable_errors_use_one_bounded_runtime_budget_and_trace(monkeypatch) -> None:
    """Runtime retries are bounded once and every retry is observable."""

    import ds_course_agent.runtime.model_runtime as runtime_module

    monkeypatch.setattr(runtime_module.config, "CHAT_MAX_RETRIES", 2)
    sleeps = []
    monkeypatch.setattr(runtime_module.time, "sleep", lambda seconds: sleeps.append(seconds))
    model = Mock()
    model.invoke.side_effect = [
        TimeoutError("timeout"),
        ConnectionError("connection lost"),
        AIMessage(content="recovered"),
    ]
    runtime = _runtime(model)

    token = begin_query_trace({"entrypoint": "model_runtime_retry"})
    try:
        assert runtime.direct_chat("question") == "recovered"
    finally:
        trace = end_query_trace(token)

    assert model.invoke.call_count == 3
    assert sleeps == [1.0, 2.0]
    retry_events = [event for event in trace["events"] if event["stage"] == "agent.retry"]
    assert [event["data"]["attempt"] for event in retry_events] == [1, 2]
    assert [event["data"]["reason"] for event in retry_events] == ["retryable", "retryable"]


def test_permanent_error_is_not_retried_or_delayed(monkeypatch) -> None:
    """Authentication/configuration errors fail closed after one attempt."""

    import ds_course_agent.runtime.model_runtime as runtime_module

    class AuthError(Exception):
        status_code = 401

    monkeypatch.setattr(runtime_module.config, "CHAT_MAX_RETRIES", 2)
    sleep = Mock()
    monkeypatch.setattr(runtime_module.time, "sleep", sleep)
    model = Mock()
    model.invoke.side_effect = AuthError("401 unauthorized")
    runtime = _runtime(model)

    token = begin_query_trace({"entrypoint": "model_runtime_permanent"})
    try:
        result = runtime.direct_chat("question")
    finally:
        trace = end_query_trace(token)

    assert "AI服务配置异常" in result
    assert model.invoke.call_count == 1
    sleep.assert_not_called()
    assert not any(event["stage"] == "agent.retry" for event in trace["events"])


def test_empty_buffered_response_keeps_semantic_retry(monkeypatch) -> None:
    """An empty successful response remains retryable under the runtime policy."""

    import ds_course_agent.runtime.model_runtime as runtime_module

    monkeypatch.setattr(runtime_module.config, "CHAT_MAX_RETRIES", 1)
    monkeypatch.setattr(runtime_module.time, "sleep", lambda _seconds: None)
    model = Mock()
    model.invoke.side_effect = [AIMessage(content="   "), AIMessage(content="answer")]
    runtime = _runtime(model)

    token = begin_query_trace({"entrypoint": "model_runtime_empty"})
    try:
        assert runtime.direct_chat("question") == "answer"
    finally:
        trace = end_query_trace(token)

    assert model.invoke.call_count == 2
    retries = [event for event in trace["events"] if event["stage"] == "agent.retry"]
    assert len(retries) == 1
    assert retries[0]["data"]["reason"] == "direct_empty_response"


def test_agent_chat_model_assigns_retry_ownership_to_runtime(monkeypatch) -> None:
    """The AgentService model must not also enable provider-level retries."""

    import langchain_openai

    import ds_course_agent.shared.llm as llm_module

    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(langchain_openai, "ChatOpenAI", FakeChatOpenAI)
    monkeypatch.setattr(llm_module.config, "USE_REMOTE_LLM", True)

    llm_module.get_chat_model(max_retries=0)

    assert captured["max_retries"] == 0
