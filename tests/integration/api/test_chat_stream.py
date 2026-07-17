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

    response = fresh_client.get(
        f"/api/chat/send/stream?session_id={session_id}&message=hello&student_id=test"
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
