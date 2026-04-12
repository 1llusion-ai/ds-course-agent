import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def fresh_client(monkeypatch):
    """Client with mocked stream function."""
    from app.routers.sessions import _sessions
    from app.state import _chat_history

    _sessions.clear()
    _chat_history.clear()

    def fake_stream_chat_with_history(message: str, session_id: str, student_id: str):
        assert message == "hello"
        assert student_id == "test"
        yield {"type": "delta", "delta": "你"}
        yield {"type": "delta", "delta": "好"}
        yield {
            "type": "final",
            "content": "你好",
            "sources": [{"reference": "《第1章 数据科学简介》第1页"}],
        }

    # Patch the actual module where chat router imports the function from
    import apps.api.app.routers.chat as chat_module
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
