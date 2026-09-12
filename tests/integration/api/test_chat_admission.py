"""Admission follows actual generation work, including disconnected SSE consumers."""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime

import pytest
from fastapi import HTTPException

import ds_course_agent.shared.config as config
from ds_course_agent.api import chat_application, chat_sessions
from ds_course_agent.api.admission import ChatAdmission
from ds_course_agent.api.schemas.chat import ChatStreamRequest
from ds_course_agent.api.state import _chat_history, _sessions


@pytest.fixture
def admission(monkeypatch):
    limiter = ChatAdmission()
    monkeypatch.setattr(config, "API_CHAT_MAX_CONCURRENT", 2)
    monkeypatch.setattr(config, "API_CHAT_MAX_PER_STUDENT", 1)
    monkeypatch.setattr(chat_application, "chat_admission", limiter)
    return limiter


def test_capacity_is_shared_between_students_and_release_is_idempotent(admission):
    alice = admission.acquire("alice")
    with pytest.raises(HTTPException) as caught:
        admission.acquire("alice")
    assert caught.value.status_code == 429
    bob = admission.acquire("bob")
    with pytest.raises(HTTPException):
        admission.acquire("carol")
    alice.release()
    alice.release()
    carol = admission.acquire("carol")
    with pytest.raises(HTTPException):
        admission.acquire("dave")
    bob.release()
    carol.release()


@pytest.mark.parametrize("path", ["/api/chat/send", "/api/chat/send/stream", "/api/chat/continue/stream"])
def test_overload_is_http_429_before_history_mutation(client, admission, path):
    _sessions["s"] = {"student_id": "alice", "title": "test"}
    _chat_history["s"] = []
    lease = admission.acquire("alice")
    try:
        response = client.post(
            path,
            headers={"x-test-student-id": "alice"},
            json={"session_id": "s", "message": "question", "message_timestamp": datetime.now().isoformat()},
        )
        assert response.status_code == 429
        assert response.headers["retry-after"] == "5"
        assert _chat_history["s"] == []
    finally:
        lease.release()


def test_disconnected_sse_consumer_does_not_release_running_worker(monkeypatch, admission):
    _sessions["s"] = {"student_id": "alice", "title": "test"}
    _chat_history["s"] = []
    release_worker = threading.Event()

    def blocking_source(**kwargs):
        yield {"type": "delta", "delta": "partial"}
        assert release_worker.wait(3)
        yield {"type": "final", "content": "complete"}

    monkeypatch.setattr(chat_application, "stream_chat_with_history", blocking_source)

    async def exercise() -> None:
        stream = await chat_application.stream_message_events(ChatStreamRequest(session_id="s", message="q"), "alice")
        await anext(stream)
        await stream.aclose()
        try:
            with pytest.raises(HTTPException):
                admission.acquire("alice")
        finally:
            release_worker.set()
        await chat_sessions.acquire_threading_lock(chat_sessions.session_operation_lock("s"))
        chat_sessions.session_operation_lock("s").release()
        lease = admission.acquire("alice")
        lease.release()

    asyncio.run(exercise())


def test_cancelled_waiter_releases_admission_without_starting_a_turn(admission):
    _sessions["s"] = {"student_id": "alice", "title": "test"}
    _chat_history["s"] = []
    lock = chat_sessions.session_operation_lock("s")
    lock.acquire()

    async def exercise() -> None:
        task = asyncio.create_task(
            chat_application.stream_message_events(ChatStreamRequest(session_id="s", message="q"), "alice")
        )
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        lease = admission.acquire("alice")
        lease.release()
        assert _chat_history["s"] == []

    try:
        asyncio.run(exercise())
    finally:
        lock.release()


def test_worker_start_failure_returns_capacity_and_removes_unaccepted_question(monkeypatch, admission):
    _sessions["s"] = {"student_id": "alice", "title": "test"}
    _chat_history["s"] = []

    def fail_start(**kwargs):
        raise RuntimeError("worker cannot start")

    monkeypatch.setattr(chat_application.chat_streaming, "launch_stream_worker", fail_start)

    async def exercise() -> None:
        with pytest.raises(RuntimeError, match="worker cannot start"):
            await chat_application.stream_message_events(ChatStreamRequest(session_id="s", message="q"), "alice")
        assert not _chat_history["s"]
        assert not chat_sessions.session_operation_lock("s").locked()
        lease = admission.acquire("alice")
        lease.release()

    asyncio.run(exercise())


def test_unexpected_worker_exception_does_not_expose_internal_details(client, monkeypatch, admission):
    _sessions["s"] = {"student_id": "alice", "title": "test"}
    _chat_history["s"] = []

    def failed_source(**kwargs):
        raise RuntimeError("secret-internal-error-marker")

    monkeypatch.setattr(chat_application, "stream_chat_with_history", failed_source)
    response = client.post(
        "/api/chat/send/stream", headers={"x-test-student-id": "alice"}, json={"session_id": "s", "message": "q"}
    )
    assert response.status_code == 200
    assert "secret-internal-error-marker" not in response.text
    assert "回答暂时无法生成" in response.text
