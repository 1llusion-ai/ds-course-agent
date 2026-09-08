import pytest

import ds_course_agent.api.core_bridge as core_bridge
from ds_course_agent.agent.routing import (
    ExecutionMode,
    RouteExecutionResult,
    RouteFamily,
    RouteIntent,
)


class _FakeService:
    def chat_with_history(self, user_input: str, session_id: str, student_id: str):
        assert user_input == "hello"
        assert session_id == "sess_1"
        assert student_id == "stu_1"
        return RouteExecutionResult(
            content="assistant reply",
            family=RouteFamily.LEARNING,
            intent=RouteIntent.CONCEPT_QA,
            execution_mode=ExecutionMode.GROUNDED_GENERATION,
            sources=[{"title": "课程资料"}],
            retrieval_attempted=True,
            used_retrieval=True,
        )

    def stream_chat_with_history(self, user_input: str, session_id: str, student_id: str):
        assert user_input == "hello"
        assert session_id == "sess_1"
        assert student_id == "stu_1"
        yield {"type": "progress", "phase": "routing", "message": "正在分析问题类型...", "stream_id": "s1"}
        yield {"type": "delta", "delta": "A"}
        yield {
            "type": "done",
            "content": "AB",
            "family": RouteFamily.LEARNING.value,
            "intent": RouteIntent.CONCEPT_QA.value,
            "execution_mode": ExecutionMode.GROUNDED_GENERATION.value,
            "retrieval_attempted": True,
            "used_retrieval": True,
        }


def test_core_bridge_chat_includes_query_trace(monkeypatch):
    monkeypatch.setattr(core_bridge, "get_agent_service", lambda: _FakeService())

    result = core_bridge.chat_with_history("hello", "sess_1", "stu_1")

    assert result["content"] == "assistant reply"
    assert result["family"] == "learning"
    assert result["intent"] == "concept_qa"
    assert result["execution_mode"] == "grounded_generation"
    assert result["retrieval_attempted"] is True
    assert result["used_retrieval"] is True
    assert result["sources"] == [{"title": "课程资料"}]
    assert "query_trace" in result
    assert result["query_trace"]["meta"]["session_id"] == "sess_1"
    assert result["query_trace"]["status"] in {"ok", "error"}
    assert any(item["stage"] == "trace.start" for item in result["query_trace"]["events"])
    assert any(item["stage"] == "trace.end" for item in result["query_trace"]["events"])


def test_core_bridge_chat_trace_records_errors(monkeypatch):
    class _BadService:
        def chat_with_history(self, user_input: str, session_id: str, student_id: str):
            raise ValueError("bad service")

    monkeypatch.setattr(core_bridge, "get_agent_service", lambda: _BadService())

    with pytest.raises(ValueError, match="bad service"):
        core_bridge.chat_with_history("hello", "sess_1", "stu_1")


def test_core_bridge_stream_final_includes_query_trace(monkeypatch):
    monkeypatch.setattr(core_bridge, "get_agent_service", lambda: _FakeService())

    events = list(core_bridge.stream_chat_with_history("hello", "sess_1", "stu_1"))

    assert events[0]["type"] == "progress"
    assert events[1]["type"] == "delta"
    assert events[-1]["type"] == "final"
    assert events[-1]["content"] == "AB"
    assert events[-1]["family"] == "learning"
    assert events[-1]["intent"] == "concept_qa"
    assert events[-1]["execution_mode"] == "grounded_generation"
    assert events[-1]["retrieval_attempted"] is True
    assert events[-1]["used_retrieval"] is True
    assert "query_trace" in events[-1]
    assert events[-1]["query_trace"]["meta"]["session_id"] == "sess_1"
