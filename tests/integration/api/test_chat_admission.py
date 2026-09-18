import asyncio
from datetime import datetime

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
