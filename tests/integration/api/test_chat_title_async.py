import asyncio
import time

from fastapi.testclient import TestClient

from ds_course_agent.api.main import app
from ds_course_agent.api.title_generation import DEFAULT_SESSION_TITLE, build_fallback_session_title


def test_stream_does_not_block_on_first_title_generation(monkeypatch):
    import ds_course_agent.api.chat_application as chat_application
    import ds_course_agent.api.chat_sessions as chat_sessions

    chat_sessions.reset_title_generation_state()

    async def slow_title(_question: str) -> str:
        await asyncio.sleep(1.2)
        return "slow-title"

    def fake_stream_chat_with_history(message: str, session_id: str, student_id: str):
        assert message == "hello"
        assert student_id == "test"
        yield {"type": "delta", "delta": "h"}
        yield {"type": "final", "content": "hello", "sources": []}

    monkeypatch.setattr(chat_sessions, "generate_session_title", slow_title)
    monkeypatch.setattr(chat_application, "stream_chat_with_history", fake_stream_chat_with_history)

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
    import ds_course_agent.api.chat_application as chat_application
    import ds_course_agent.api.chat_sessions as chat_sessions

    chat_sessions.reset_title_generation_state()

    async def slow_title(_question: str) -> str:
        await asyncio.sleep(1.2)
        return "slow-title"

    def fake_chat_with_history(message: str, session_id: str, student_id: str):
        assert message == "hello"
        assert student_id == "test"
        return {"content": "hello", "used_retrieval": False, "sources": []}

    monkeypatch.setattr(chat_sessions, "generate_session_title", slow_title)
    monkeypatch.setattr(chat_application, "chat_with_history", fake_chat_with_history)

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
    from datetime import datetime, timezone

    import ds_course_agent.api.chat_sessions as chat_sessions
    from ds_course_agent.api.session_repository import SessionRecord

    chat_sessions.reset_title_generation_state()
    session_id = "title-immediate"
    question = "菲律宾的现任总统是谁"
    now = datetime.now(timezone.utc)
    chat_sessions._repository().create_session(
        SessionRecord(
            session_id=session_id,
            title=DEFAULT_SESSION_TITLE,
            title_source="default",
            student_id="test",
            created_at=now,
            updated_at=now,
        )
    )

    created_coroutines = []

    def fake_create_task(coro):
        created_coroutines.append(coro)
        coro.close()
        return object()

    monkeypatch.setattr(chat_sessions.asyncio, "create_task", fake_create_task)

    chat_sessions.schedule_title_generation(session_id, question, is_first_message=True)

    session = chat_sessions._repository().get_session("test", session_id)
    assert session is not None
    assert session.title == build_fallback_session_title(question)
    assert session.title != DEFAULT_SESSION_TITLE
    assert session.title_source == "heuristic"
    assert session.title_generation_pending is True
    assert created_coroutines
