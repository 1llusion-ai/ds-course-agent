import time
import asyncio

from fastapi.testclient import TestClient

from ds_course_agent.api.main import app
from ds_course_agent.api.title_generation import DEFAULT_SESSION_TITLE, build_fallback_session_title


def test_stream_does_not_block_on_first_title_generation(monkeypatch):
    from ds_course_agent.api.state import _chat_history, _sessions
    import ds_course_agent.api.routers.chat as chat_module

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
    response = client.post(
        "/api/chat/send/stream",
        headers={"x-test-student-id": "test"},
        json={"session_id": session_id, "message": "hello"},
    )
    elapsed = time.perf_counter() - started

    assert response.status_code == 200
    assert '"type": "delta"' in response.text
    assert elapsed < 1.0


def test_post_send_does_not_block_on_first_title_generation(monkeypatch):
    from ds_course_agent.api.state import _chat_history, _sessions
    import ds_course_agent.api.routers.chat as chat_module

    _sessions.clear()
    _chat_history.clear()
    chat_module._title_gen_cache.clear()

    async def slow_title(_question: str) -> str:
        await asyncio.sleep(1.2)
        return "slow-title"

    def fake_chat_with_history(message: str, session_id: str, student_id: str):
        assert message == "hello"
        assert student_id == "test"
        return {"content": "hello", "used_retrieval": False, "sources": []}

    monkeypatch.setattr(chat_module, "_generate_session_title", slow_title)
    monkeypatch.setattr(chat_module, "chat_with_history", fake_chat_with_history)

    client = TestClient(app)
    session_resp = client.post(
        "/api/sessions",
        json={"title": "new session", "student_id": "test"},
    )
    assert session_resp.status_code == 200
    session_id = session_resp.json()["id"]

    started = time.perf_counter()
    response = client.post(
        "/api/chat/send",
        json={"session_id": session_id, "message": "hello", "student_id": "test"},
    )
    elapsed = time.perf_counter() - started

    assert response.status_code == 200
    assert response.json()["message"]["content"] == "hello"
    assert elapsed < 1.0


def test_schedule_title_generation_sets_immediate_fallback(monkeypatch):
    from ds_course_agent.api.state import _sessions
    import ds_course_agent.api.routers.chat as chat_module

    _sessions.clear()
    chat_module._title_gen_cache.clear()
    session_id = "title-immediate"
    question = "菲律宾的现任总统是谁"
    _sessions[session_id] = {
        "title": DEFAULT_SESSION_TITLE,
        "title_source": "default",
        "student_id": "test",
        "created_at": "2026-07-17T10:00:00",
        "updated_at": "2026-07-17T10:00:00",
        "message_count": 0,
    }

    created_coroutines = []

    def fake_create_task(coro):
        created_coroutines.append(coro)
        coro.close()
        return object()

    monkeypatch.setattr(chat_module.asyncio, "create_task", fake_create_task)

    chat_module._schedule_title_generation(session_id, question, is_first_message=True)

    assert _sessions[session_id]["title"] == build_fallback_session_title(question)
    assert _sessions[session_id]["title"] != DEFAULT_SESSION_TITLE
    assert _sessions[session_id]["title_source"] == "heuristic"
    assert _sessions[session_id]["title_generation_pending"] is True
    assert created_coroutines
