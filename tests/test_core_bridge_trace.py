import apps.api.app.core_bridge as core_bridge


class _FakeService:
    def chat_with_history(self, user_input: str, session_id: str, student_id: str):
        assert user_input == "hello"
        assert session_id == "sess_1"
        assert student_id == "stu_1"
        return "assistant reply"

    def stream_chat_with_history(self, user_input: str, session_id: str, student_id: str):
        assert user_input == "hello"
        assert session_id == "sess_1"
        assert student_id == "stu_1"
        yield {"type": "delta", "delta": "A"}
        yield {"type": "done", "content": "AB"}


def test_core_bridge_chat_includes_query_trace(monkeypatch):
    monkeypatch.setattr(core_bridge, "get_agent_service", lambda: _FakeService())

    result = core_bridge.chat_with_history("hello", "sess_1", "stu_1")

    assert result["content"] == "assistant reply"
    assert "trace" in result
    assert result["trace"]["meta"]["entrypoint"] == "chat_with_history"
    assert result["trace"]["status"] in {"ok", "error"}
    assert any(item["stage"] == "bridge.chat_with_history.service_ready" for item in result["trace"]["events"])


def test_core_bridge_chat_trace_records_errors(monkeypatch):
    class _BadService:
        def chat_with_history(self, user_input: str, session_id: str, student_id: str):
            raise ValueError("bad service")

    monkeypatch.setattr(core_bridge, "get_agent_service", lambda: _BadService())

    result = core_bridge.chat_with_history("hello", "sess_1", "stu_1")

    assert "Agent调用出错" in result["content"]
    trace = result["trace"]
    assert trace["errors"]
    assert trace["errors"][0]["stage"] == "bridge.chat_with_history.failed"
    assert trace["errors"][0]["type"] == "ValueError"


def test_core_bridge_stream_final_includes_query_trace(monkeypatch):
    monkeypatch.setattr(core_bridge, "get_agent_service", lambda: _FakeService())

    events = list(core_bridge.stream_chat_with_history("hello", "sess_1", "stu_1"))

    assert events[0]["type"] == "delta"
    assert events[-1]["type"] == "final"
    assert events[-1]["content"] == "AB"
    assert "trace" in events[-1]
    assert events[-1]["trace"]["meta"]["entrypoint"] == "stream_chat_with_history"

