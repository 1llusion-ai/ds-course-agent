import pytest
from fastapi.testclient import TestClient

from ds_course_agent.api.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def fresh_client(monkeypatch):
    """Client with mocked stream function."""
    from ds_course_agent.api.state import _chat_history, _sessions

    _sessions.clear()
    _chat_history.clear()

    def fake_stream_chat_with_history(message: str, session_id: str, student_id: str):
        assert message == "hello"
        assert student_id == "test"
        yield {
            "type": "progress",
            "phase": "routing",
            "message": "正在分析问题类型...",
            "stream_id": "s1",
            "tool": "course_rag_tool",
            "details": {"found_count": 2},
        }
        yield {
            "type": "progress",
            "phase": "generation",
            "message": "正在生成回答...",
            "route": "generic_agent",
            "stream_id": "s1",
        }
        yield {"type": "delta", "delta": "你"}
        yield {"type": "delta", "delta": "好"}
        yield {
            "type": "final",
            "content": "你好",
            "sources": [{"reference": "《第1章 数据科学简介》第1页"}],
        }

    # Patch the actual module where chat router imports the function from
    import ds_course_agent.api.routers.chat as chat_module

    monkeypatch.setattr(chat_module, "stream_chat_with_history", fake_stream_chat_with_history)
    return TestClient(app)


def test_stream_endpoint_returns_real_sse(fresh_client):
    session_resp = fresh_client.post(
        "/api/sessions",
        json={
            "title": "stream test",
            "student_id": "test",
        },
    )
    assert session_resp.status_code == 200
    session_id = session_resp.json()["id"]

    response = fresh_client.post(
        "/api/chat/send/stream",
        headers={"x-test-student-id": "test"},
        json={"session_id": session_id, "message": "hello"},
    )

    assert response.status_code == 200
    assert '"type": "progress"' in response.text
    assert '"tool": "course_rag_tool"' in response.text
    assert '"found_count": 2' in response.text
    assert '"type": "delta"' in response.text
    assert '"type": "final"' in response.text
    assert "你好" in response.text

    history_resp = fresh_client.get(f"/api/chat/history/{session_id}?student_id=test")
    assert history_resp.status_code == 200
    messages = history_resp.json()["messages"]

    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "hello"
    assert messages[-1]["role"] == "assistant"
    assert messages[-1]["content"] == "你好"
    assert messages[-1]["sources"] == [{"reference": "《第1章 数据科学简介》第1页"}]
    assert messages[-1]["progress_events"][0]["phase"] == "routing"
    assert messages[-1]["progress_events"][0]["details"]["found_count"] == 2
    assert messages[-1]["progress_events"][1]["route"] == "generic_agent"


def test_progress_details_are_compacted_for_history():
    from ds_course_agent.api.routers.chat import _compact_progress_details_for_history

    details = {
        "found_count": 10,
        "results": [
            {
                "title": "标题" * 400,
                "url": f"https://example.com/{index}",
                "snippet": "摘要" * 400,
            }
            for index in range(10)
        ],
    }

    compacted = _compact_progress_details_for_history(details)

    assert compacted["found_count"] == 10
    assert len(compacted["results"]) == 6
    assert compacted["results"][-1]["_truncated_items"] == 5
    assert len(compacted["results"][0]["title"]) <= 500
    assert len(compacted["results"][0]["snippet"]) <= 500


def test_stream_records_blocked_web_search_turn_state(monkeypatch):
    from ds_course_agent.api.state import _chat_history, _sessions

    _sessions.clear()
    _chat_history.clear()

    def fake_stream_chat_with_history(message: str, session_id: str, student_id: str, web_search: bool = False):
        assert message == "今天厦门的天气怎么样？"
        assert student_id == "test"
        assert web_search is True
        yield {
            "type": "progress",
            "phase": "web_search_scope",
            "message": "联网搜索限于教学相关资料",
            "route": "web_search",
            "stream_id": "blocked-1",
            "tool": "web_search_tool",
        }
        yield {
            "type": "final",
            "content": "这个问题不属于课程助教的回答范围，所以本次不进行通用联网搜索。",
            "route": "web_search",
            "used_retrieval": False,
            "sources": [],
        }

    import ds_course_agent.api.routers.chat as chat_module

    monkeypatch.setattr(chat_module, "stream_chat_with_history", fake_stream_chat_with_history)
    client = TestClient(app)

    session_resp = client.post(
        "/api/sessions",
        headers={"x-test-student-id": "test"},
        json={"title": "stream test"},
    )
    assert session_resp.status_code == 200
    session_id = session_resp.json()["id"]

    response = client.post(
        "/api/chat/send/stream",
        headers={"x-test-student-id": "test"},
        json={
            "session_id": session_id,
            "message": "今天厦门的天气怎么样？",
            "web_search": True,
        },
    )

    assert response.status_code == 200
    assert '"web_search_requested": true' in response.text
    assert '"web_search_used": false' in response.text
    assert '"web_search_status": "blocked_by_scope"' in response.text

    history_resp = client.get(f"/api/chat/history/{session_id}", headers={"x-test-student-id": "test"})
    assert history_resp.status_code == 200
    assistant_message = history_resp.json()["messages"][-1]
    assert assistant_message["web_search_requested"] is True
    assert assistant_message["web_search_used"] is False
    assert assistant_message["web_search_status"] == "blocked_by_scope"


def test_web_search_turn_state_records_stream_search_error():
    from ds_course_agent.api.routers.chat import _web_search_turn_fields

    fields = _web_search_turn_fields(
        requested=True,
        used_retrieval=False,
        progress_events=[{"phase": "web_search_error", "message": "联网搜索未获得可用结果"}],
        sources=[],
    )

    assert fields["web_search_requested"] is True
    assert fields["web_search_used"] is False
    assert fields["web_search_status"] == "error"


def test_history_reports_pending_generation_and_cancel_sets_job_event():
    import threading

    from ds_course_agent.api.routers.chat import _register_active_stream_job, _unregister_active_stream_job
    from ds_course_agent.api.state import _chat_history, _sessions

    _sessions.clear()
    _chat_history.clear()
    client = TestClient(app)
    session_resp = client.post(
        "/api/sessions",
        headers={"x-test-student-id": "test"},
        json={"title": "pending test"},
    )
    assert session_resp.status_code == 200
    session_id = session_resp.json()["id"]
    cancel_event = threading.Event()

    try:
        started_at = _register_active_stream_job(session_id, "test", cancel_event)
        history_resp = client.get(f"/api/chat/history/{session_id}", headers={"x-test-student-id": "test"})
        assert history_resp.status_code == 200
        history = history_resp.json()
        assert history["pending_generation"] is True
        assert history["pending_started_at"].startswith(started_at.isoformat()[:19])

        cancel_resp = client.post(f"/api/chat/cancel/{session_id}", headers={"x-test-student-id": "test"})
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["cancelled"] is True
        assert cancel_event.is_set()
    finally:
        _unregister_active_stream_job(session_id)
