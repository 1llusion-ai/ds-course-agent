"""Web answers exercise real service/runtime wiring without external requests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk

from ds_course_agent.agent.hooks import HookManager
from ds_course_agent.agent.routing import (
    ExecutionMode,
    QueryContext,
    RetrievalPolicy,
    RouteDecision,
    RouteFamily,
    RouteIntent,
    RouteState,
)
from ds_course_agent.agent.service import AgentService
from ds_course_agent.tools.registry import ToolRegistry
from ds_course_agent.tools.web_search import WebSearchResponse, WebSearchResult


@pytest.mark.parametrize("mode", ["sync", "stream", "empty_stream"])
def test_web_answer_uses_direct_model_with_real_service_runtime(monkeypatch, mode) -> None:
    """Removing AgentService.llm must not reroute web answers into a tool graph."""

    import ds_course_agent.agent.service as service_module
    import ds_course_agent.shared.config as config

    llm = Mock()
    llm.invoke.return_value = AIMessage(content="OPD answer [1]")
    llm.stream.return_value = iter([] if mode == "empty_stream" else [AIMessageChunk(content="OPD answer [1]")])
    monkeypatch.setattr(config, "USE_REMOTE_LLM", True)
    monkeypatch.setattr(config, "WEB_FETCH_ENABLED", False)
    monkeypatch.setattr(config, "WEB_SEARCH_TEACHING_SCOPE_ENABLED", False)
    monkeypatch.setattr(service_module, "get_chat_model", lambda **kwargs: llm)
    monkeypatch.setattr(service_module, "get_rag_tool_registry", ToolRegistry)
    response = WebSearchResponse(
        query="OPD是什么？",
        provider="test",
        results=[WebSearchResult(title="OPD", url="https://example.com/opd", snippet="OPD evidence", provider="test")],
        evidence_context="[1] OPD evidence https://example.com/opd",
    )
    search = Mock(return_value=response)
    monkeypatch.setattr("ds_course_agent.tools.web_search.search_web", search)
    service = AgentService()
    service.hooks = HookManager([])
    service.chat = Mock(side_effect=AssertionError("Web answers must not call a tool graph"))
    service.model_runtime._create_agent = Mock(side_effect=AssertionError("Web answers must not bind tools"))
    assert not hasattr(service, "llm")
    messages = []
    state = RouteState(
        context=QueryContext(
            original_query="OPD是什么？",
            normalized_query="opd是什么",
            session_id="web",
            student_id="s",
            chat_history=[],
        ),
        decision=RouteDecision(
            family=RouteFamily.EXTERNAL_RESEARCH,
            intent=RouteIntent.WEB_RESEARCH,
            execution_mode=ExecutionMode.WEB_PIPELINE,
            confidence=1.0,
            retrieval_policy=RetrievalPolicy.REQUIRED,
        ),
        student_id="s",
        session_id="web",
        chat_history=[],
        history=SimpleNamespace(add_messages=messages.extend),
    )
    monkeypatch.setattr(service, "_prepare_query_route", lambda *args, **kwargs: state)

    if mode == "sync":
        result = service.chat_with_history("OPD是什么？", "web", student_id="s", web_search=True)
        content, sources, used = result.content, result.sources, result.used_retrieval
    else:
        events = list(service.stream_chat_with_history("OPD是什么？", "web", student_id="s", web_search=True))
        assert not any(event["type"] == "error" for event in events)
        final = events[-1]
        assert final["type"] == "done"
        content, sources, used = final["content"], final["sources"], final["used_retrieval"]
        assert "".join(event["delta"] for event in events if event["type"] == "delta") == content

    assert content == "OPD answer [1]"
    assert sources[0]["url"] == "https://example.com/opd"
    assert used is True
    assert [message.type for message in messages] == ["human", "ai"]
    search.assert_called_once()
    service.chat.assert_not_called()
    service.model_runtime._create_agent.assert_not_called()
    assert llm.invoke.call_count == (mode != "stream")
    assert llm.stream.call_count == (mode != "sync")
