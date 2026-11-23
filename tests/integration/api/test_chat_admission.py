import asyncio
import json
import threading
from datetime import datetime

import httpx
import pytest

from ds_course_agent.api.main import app


def test_full_generation_admission_rejects_all_chat_generation_paths(client, monkeypatch):
    import ds_course_agent.api.chat_application as chat_application
    from ds_course_agent.api.chat_application import _GenerationAdmission

    session_response = client.post("/api/sessions", json={"title": "admission", "student_id": "student001"})
    assert session_response.status_code == 200
    session_id = session_response.json()["id"]

    admission = _GenerationAdmission(active_limit=1, queue_limit=0, queue_timeout=1.0)
    lease = asyncio.run(admission.acquire())
    monkeypatch.setattr(chat_application, "_generation_admission", admission)
    try:
        send_response = client.post(
            "/api/chat/send",
            headers={"x-test-student-id": "student001"},
            json={"session_id": session_id, "message": "hello"},
        )
        stream_response = client.post(
            "/api/chat/send/stream",
            headers={"x-test-student-id": "student001"},
            json={"session_id": session_id, "message": "hello"},
        )
        continue_response = client.post(
            "/api/chat/continue/stream",
            headers={"x-test-student-id": "student001"},
            json={"session_id": session_id, "message_timestamp": datetime.now().isoformat()},
        )
    finally:
        lease.release()

    for response in (send_response, stream_response, continue_response):
        assert response.status_code == 429
        assert response.headers["retry-after"] == "1"

    assert stream_response.headers["content-type"].startswith("application/json")


def test_disconnected_stream_retains_generation_slot_until_replay_can_finish(monkeypatch):
    from ds_course_agent.api import chat_application

    monkeypatch.setattr(chat_application, "_generation_admission", chat_application._GenerationAdmission(1, 1, 0.1))
    finish_answer = threading.Event()

    def stream_answer(**kwargs):
        yield {"type": "delta", "delta": "partial"}
        assert finish_answer.wait(timeout=5)
        yield {"type": "final", "content": "partial answer completed"}

    monkeypatch.setattr(chat_application, "stream_chat_with_history", stream_answer)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            first_session = (await client.post("/api/sessions", json={"title": "first"})).json()["id"]
            other_headers = {"x-test-student-id": "student002"}
            other_session = (await client.post("/api/sessions", json={"title": "other"}, headers=other_headers)).json()[
                "id"
            ]
            disconnect = asyncio.Event()
            body = json.dumps({"session_id": first_session, "message": "question"}).encode()

            async def receive():
                nonlocal body
                if body:
                    request, body = body, b""
                    return {"type": "http.request", "body": request}
                await disconnect.wait()
                return {"type": "http.disconnect"}

            async def send(message):
                if b'"delta": "partial"' in message.get("body", b""):
                    disconnect.set()

            try:
                await asyncio.wait_for(
                    app(
                        {
                            "type": "http",
                            "method": "POST",
                            "path": "/api/chat/send/stream",
                            "query_string": b"",
                            "headers": [(b"content-type", b"application/json")],
                        },
                        receive,
                        send,
                    ),
                    timeout=2,
                )
                other_question = {"session_id": other_session, "message": "other question"}
                rejected = await client.post("/api/chat/send", json=other_question, headers=other_headers)
                assert rejected.status_code == 429
            finally:
                finish_answer.set()

            replay = await client.get(f"/api/chat/resume/{first_session}")
            assert replay.status_code == 200
            assert '"generation_status": "completed"' in replay.text
            assert "partial answer completed" in replay.text
            accepted = await client.post("/api/chat/send", json=other_question, headers=other_headers)
            assert accepted.status_code == 200

    asyncio.run(scenario())


def test_worker_start_failure_clears_turn_and_allows_retry(monkeypatch):
    from ds_course_agent.api import chat_application

    admission = chat_application._GenerationAdmission(1, 0, 1.0)
    monkeypatch.setattr(chat_application, "_generation_admission", admission)
    start_thread = threading.Thread.start
    fail_worker_start = True

    def start(thread):
        if fail_worker_start and thread.name.startswith("chat-sse-"):
            raise RuntimeError("could not start stream worker")
        return start_thread(thread)

    monkeypatch.setattr(threading.Thread, "start", start)

    async def scenario():
        nonlocal fail_worker_start
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            session_id = (await client.post("/api/sessions", json={"title": "retry"})).json()["id"]
            question = {"session_id": session_id, "message": "question"}

            failed = await client.post("/api/chat/send/stream", json=question)
            assert failed.status_code == 500
            history = await client.get(f"/api/chat/history/{session_id}")
            assert history.json()["messages"] == []
            assert history.json()["active_stream"] is None
            replay = await client.get(f"/api/chat/resume/{session_id}")
            assert replay.status_code == 404

            fail_worker_start = False
            retry = await client.post("/api/chat/send/stream", json=question)
            assert retry.status_code == 200
            assert '"generation_status": "completed"' in retry.text

    asyncio.run(scenario())


def test_invalid_continuation_returns_http_error_and_releases_slot(client, monkeypatch):
    from ds_course_agent.api import chat_application

    monkeypatch.setattr(chat_application, "_generation_admission", chat_application._GenerationAdmission(1, 0, 1.0))
    session_id = client.post("/api/sessions", json={"title": "invalid continuation"}).json()["id"]

    invalid = client.post(
        "/api/chat/continue/stream",
        json={"session_id": session_id, "message_timestamp": datetime.now().isoformat()},
    )
    assert invalid.status_code == 409

    next_turn = client.post("/api/chat/send", json={"session_id": session_id, "message": "question"})
    assert next_turn.status_code == 200


def test_cancelling_send_waiting_for_same_session_releases_slot(monkeypatch):
    from ds_course_agent.api import chat_application

    monkeypatch.setattr(chat_application, "_generation_admission", chat_application._GenerationAdmission(2, 0, 1.0))
    finish_first = threading.Event()

    async def scenario():
        loop = asyncio.get_running_loop()
        first_started = asyncio.Event()

        def stream_answer(**kwargs):
            loop.call_soon_threadsafe(first_started.set)
            assert finish_first.wait(timeout=5)
            yield {"type": "final", "content": "first answer"}

        monkeypatch.setattr(chat_application, "stream_chat_with_history", stream_answer)

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            first_session = (await client.post("/api/sessions", json={"title": "first"})).json()["id"]
            other_session = (await client.post("/api/sessions", json={"title": "other"})).json()["id"]
            question = {"session_id": first_session, "message": "question"}
            other_question = {"session_id": other_session, "message": "other question"}

            first = asyncio.create_task(client.post("/api/chat/send/stream", json=question))
            try:
                await asyncio.wait_for(first_started.wait(), timeout=2)
                waiting = asyncio.create_task(client.post("/api/chat/send/stream", json=question))
                try:
                    await asyncio.sleep(0)
                    rejected = await client.post("/api/chat/send", json=other_question)
                    assert rejected.status_code == 429
                finally:
                    waiting.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await waiting

                accepted = await client.post("/api/chat/send", json=other_question)
                assert accepted.status_code == 200
            finally:
                finish_first.set()
                response = await asyncio.wait_for(first, timeout=2)
                assert '"generation_status": "completed"' in response.text

    asyncio.run(scenario())
