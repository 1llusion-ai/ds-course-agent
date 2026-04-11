from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_stream_endpoint_returns_real_sse(monkeypatch):
    from app.routers.sessions import _sessions
    from app.state import _chat_history
    import app.routers.chat as chat_router

    _sessions.clear()
    _chat_history.clear()

    session_resp = client.post(
        "/api/sessions",
        json={
            "title": "stream test",
            "student_id": "test",
        },
    )
    assert session_resp.status_code == 200
    session_id = session_resp.json()["id"]

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

    monkeypatch.setattr(chat_router, "stream_chat_with_history", fake_stream_chat_with_history)

    response = client.get(
        f"/api/chat/send/stream?session_id={session_id}&message=hello&student_id=test"
    )

    assert response.status_code == 200
    assert '"type": "delta"' in response.text
    assert '"type": "final"' in response.text
    assert "你好" in response.text

    history_resp = client.get(f"/api/chat/history/{session_id}?student_id=test")
    assert history_resp.status_code == 200
    messages = history_resp.json()["messages"]

    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "hello"
    assert messages[-1]["role"] == "assistant"
    assert messages[-1]["content"] == "你好"
    assert messages[-1]["sources"] == [{"reference": "《第1章 数据科学简介》第1页"}]
