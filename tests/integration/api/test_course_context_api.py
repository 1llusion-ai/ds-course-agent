from __future__ import annotations

import threading
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from ds_course_agent.api import chat_application, chat_sessions
from ds_course_agent.api.course_context import course_catalog
from ds_course_agent.api.schemas.chat import ChatMessage
from ds_course_agent.api.session_repository import DEFAULT_COURSE_ID, SessionRecord, SQLiteSessionRepository
from ds_course_agent.api.stream_jobs import stream_job_registry

HEADERS = {"x-test-student-id": "course-student"}


@pytest.fixture(autouse=True)
def isolated_stream_jobs():
    stream_job_registry.clear()
    yield
    stream_job_registry.clear()


def _session(course_id: str, student_id: str = "course-student") -> SessionRecord:
    now = datetime.now(timezone.utc)
    return SessionRecord(
        session_id="shared-session",
        student_id=student_id,
        course_id=course_id,
        title="课程对话",
        title_source="manual",
        created_at=now,
        updated_at=now,
    )


def test_catalog_lists_course_status_without_runtime_paths(client):
    response = client.get("/api/courses")
    assert response.status_code == 200
    courses = {item["course_id"]: item for item in response.json()["courses"]}
    assert courses[DEFAULT_COURSE_ID]["status"] == "ready"
    assert courses["digital-literacy"]["status"] == "ready"
    assert "persist_directory" not in response.text
    assert "manifest_path" not in response.text


def test_unknown_courses_rejected(client):
    unknown = client.post("/api/sessions", json={"course_id": "unknown-course"}, headers=HEADERS)
    assert unknown.status_code == 422
    malformed = client.post("/api/sessions", json={"course_id": "../../bad"}, headers=HEADERS)
    assert malformed.status_code == 422


def test_same_session_id_keeps_history_owner_resume_cancel_and_delete_in_course(client):
    repository = SQLiteSessionRepository()
    repository.create_session(_session(DEFAULT_COURSE_ID))
    repository.create_session(_session("digital-literacy", "other-student"))
    chat_sessions.append_message_locked("shared-session", ChatMessage(role="user", content="数据科学问题"))
    chat_sessions.append_message_locked(
        "shared-session", ChatMessage(role="user", content="数字素养问题"), "digital-literacy"
    )
    default_job = stream_job_registry.register(
        session_id="shared-session",
        student_id="course-student",
        cancel_event=threading.Event(),
        message_timestamp=datetime.now(),
    )
    other_job = stream_job_registry.register(
        session_id="shared-session",
        student_id="other-student",
        course_id="digital-literacy",
        cancel_event=threading.Event(),
        message_timestamp=datetime.now(),
    )
    default_job.publish({"type": "delta", "delta": "数据科学流"})
    other_job.publish({"type": "delta", "delta": "数字素养流"})

    own = client.get("/api/chat/history/shared-session", headers=HEADERS)
    assert own.status_code == 200
    assert [item["content"] for item in own.json()["messages"]] == ["数据科学问题"]
    assert own.json()["active_stream"]["content"] == "数据科学流"
    forbidden = client.get("/api/chat/history/shared-session?course_id=digital-literacy", headers=HEADERS)
    assert forbidden.status_code == 403
    other_headers = {"x-test-student-id": "other-student"}
    other = client.get("/api/chat/history/shared-session?course_id=digital-literacy", headers=other_headers)
    assert [item["content"] for item in other.json()["messages"]] == ["数字素养问题"]
    assert other.json()["active_stream"]["content"] == "数字素养流"
    assert chat_application.get_resume_job("shared-session", "other-student", "digital-literacy") is other_job
    client.post("/api/chat/cancel/shared-session?course_id=digital-literacy", headers=other_headers)
    assert other_job.cancel_event.is_set()
    assert not default_job.cancel_event.is_set()
    deleted = client.delete("/api/sessions/shared-session?course_id=digital-literacy", headers=other_headers)
    assert deleted.status_code == 200
    assert repository.find_session("shared-session", "digital-literacy") is None
    assert repository.find_session("shared-session") is not None
    assert [item["content"] for item in chat_sessions.list_messages("shared-session")] == ["数据科学问题"]


def test_ready_nondefault_course_send_passes_explicit_course_to_bridge(client, monkeypatch):
    import ds_course_agent.api.course_context as context_module

    manifests = tuple(
        replace(manifest, status="ready", index=course_catalog().require(DEFAULT_COURSE_ID).index)
        if str(manifest.course_id) == "digital-literacy"
        else manifest
        for manifest in course_catalog().list()
    )
    monkeypatch.setattr(context_module, "course_catalog", lambda: type(course_catalog())(manifests))
    captured = {}

    def fake_chat(message, session_id, student_id, course_id):
        captured.update(course_id=course_id, student_id=student_id, session_id=session_id)
        return {"content": "数字素养回答"}

    monkeypatch.setattr(chat_application, "chat_with_history", fake_chat)
    created = client.post("/api/sessions", json={"course_id": "digital-literacy"}, headers=HEADERS).json()
    response = client.post(
        "/api/chat/send",
        json={"course_id": "digital-literacy", "session_id": created["id"], "message": "数字素养"},
        headers=HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["course_id"] == "digital-literacy"
    assert captured["course_id"] == "digital-literacy"
