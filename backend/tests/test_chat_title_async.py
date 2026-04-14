import time
import asyncio

from fastapi.testclient import TestClient

from apps.api.app.main import app


def test_stream_does_not_block_on_first_title_generation(monkeypatch):
    from apps.api.app.state import _chat_history, _sessions
    import apps.api.app.routers.chat as chat_module

    _sessions.clear()
    _chat_history.clear()
    chat_module._title_gen_cache.clear()

    async def slow_title(_question: str) -> str:
        await asyncio.sleep(1.2)
        return "slow-title"

    def fake_stream_chat_with_history(message: str, session_id: str, student_id: str):
        assert message == "hello"
        assert student_id == "test"
        yield {"type": "delta", "delta": "h"}
        yield {"type": "final", "content": "hello", "sources": []}

    monkeypatch.setattr(chat_module, "_generate_session_title", slow_title)
    monkeypatch.setattr(chat_module, "stream_chat_with_history", fake_stream_chat_with_history)

    client = TestClient(app)
    session_resp = client.post(
        "/api/sessions",
        json={"title": "new session", "student_id": "test"},
    )
    assert session_resp.status_code == 200
    session_id = session_resp.json()["id"]

    started = time.perf_counter()
    response = client.get(
        f"/api/chat/send/stream?session_id={session_id}&message=hello&student_id=test"
    )
    elapsed = time.perf_counter() - started

    assert response.status_code == 200
    assert '"type": "delta"' in response.text
    assert elapsed < 1.0
