import pytest
from fastapi.testclient import TestClient

from ds_course_agent.api.main import app


@pytest.fixture(autouse=True)
def clear_stream_jobs():
    from ds_course_agent.api.stream_jobs import stream_job_registry

    stream_job_registry.clear()
    yield
    stream_job_registry.clear()


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
            "family": "learning",
            "intent": "concept_qa",
            "execution_mode": "grounded_generation",
            "stream_id": "s1",
        }
        yield {"type": "delta", "delta": "你"}
        yield {"type": "delta", "delta": "好"}
        yield {
            "type": "final",
            "content": "你好",
            "sources": [{"reference": "《第1章 数据科学简介》第1页"}],
            "used_retrieval": True,
            "family": "learning",
            "intent": "concept_qa",
            "execution_mode": "grounded_generation",
            "degraded": False,
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

    response = fresh_client.post(
        "/api/chat/send/stream",
        headers={"x-test-student-id": "test"},
        json={"session_id": session_id, "message": "hello"},
    )

    assert response.status_code == 200
    assert '"type": "snapshot"' in response.text
    assert '"type": "progress"' in response.text
    assert '"tool": "course_rag_tool"' in response.text
    assert '"found_count": 2' in response.text
    assert '"type": "delta"' in response.text
    assert '"type": "final"' in response.text
    assert '"family": "learning"' in response.text
    assert '"intent": "concept_qa"' in response.text
    assert '"execution_mode": "grounded_generation"' in response.text
    assert '"route"' not in response.text
    assert "你好" in response.text

    history_resp = fresh_client.get(f"/api/chat/history/{session_id}?student_id=test")
    assert history_resp.status_code == 200
    messages = history_resp.json()["messages"]

    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "hello"
    assert messages[-1]["role"] == "assistant"
    assert messages[-1]["content"] == "你好"
    assert messages[-1]["sources"] == [{"reference": "《第1章 数据科学简介》第1页"}]
    assert messages[-1]["family"] == "learning"
    assert messages[-1]["intent"] == "concept_qa"
    assert messages[-1]["execution_mode"] == "grounded_generation"
    assert "route" not in messages[-1]
    assert messages[-1]["progress_events"][0]["phase"] == "routing"
    assert messages[-1]["progress_events"][0]["details"]["found_count"] == 2
    assert messages[-1]["progress_events"][1]["intent"] == "concept_qa"


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


def test_stream_records_blocked_web_search_turn_state(monkeypatch):
    from ds_course_agent.api.state import _chat_history, _sessions

    _sessions.clear()
    _chat_history.clear()

    def fake_stream_chat_with_history(message: str, session_id: str, student_id: str, web_search: bool = False):
        assert message == "今天厦门的天气怎么样？"
        assert student_id == "test"
        assert web_search is True
        yield {
            "type": "progress",
            "phase": "web_search_scope",
            "message": "联网搜索限于教学相关资料",
            "family": "external_research",
            "intent": "web_research",
            "execution_mode": "web_pipeline",
            "stream_id": "blocked-1",
            "tool": "web_search_tool",
        }
        yield {
            "type": "final",
            "content": "这个问题不属于课程助教的回答范围，所以本次不进行通用联网搜索。",
            "family": "external_research",
            "intent": "web_research",
            "execution_mode": "web_pipeline",
            "used_retrieval": False,
            "sources": [],
        }

    import ds_course_agent.api.routers.chat as chat_module

    monkeypatch.setattr(chat_module, "stream_chat_with_history", fake_stream_chat_with_history)
    client = TestClient(app)

    session_resp = client.post(
        "/api/sessions",
        headers={"x-test-student-id": "test"},
        json={"title": "stream test"},
    )
    assert session_resp.status_code == 200
    session_id = session_resp.json()["id"]

    response = client.post(
        "/api/chat/send/stream",
        headers={"x-test-student-id": "test"},
        json={
            "session_id": session_id,
            "message": "今天厦门的天气怎么样？",
            "web_search": True,
        },
    )

    assert response.status_code == 200
    assert '"web_search_requested": true' in response.text
    assert '"web_search_used": false' in response.text
    assert '"web_search_status": "blocked_by_scope"' in response.text

    history_resp = client.get(f"/api/chat/history/{session_id}", headers={"x-test-student-id": "test"})
    assert history_resp.status_code == 200
    assistant_message = history_resp.json()["messages"][-1]
    assert assistant_message["web_search_requested"] is True
    assert assistant_message["web_search_used"] is False
    assert assistant_message["web_search_status"] == "blocked_by_scope"


def test_web_search_turn_state_records_stream_search_error():
    from ds_course_agent.api.routers.chat import _web_search_turn_fields

    fields = _web_search_turn_fields(
        requested=True,
        used_retrieval=False,
        progress_events=[{"phase": "web_search_error", "message": "联网搜索未获得可用结果"}],
        sources=[],
    )

    assert fields["web_search_requested"] is True
    assert fields["web_search_used"] is False
    assert fields["web_search_status"] == "error"


def test_history_exposes_active_stream_snapshot_and_cancel_sets_job_event():
    import threading
    from datetime import datetime

    from ds_course_agent.api.state import _chat_history, _sessions
    from ds_course_agent.api.stream_jobs import stream_job_registry

    _sessions.clear()
    _chat_history.clear()
    client = TestClient(app)
    session_resp = client.post(
        "/api/sessions",
        headers={"x-test-student-id": "test"},
        json={"title": "pending test"},
    )
    assert session_resp.status_code == 200
    session_id = session_resp.json()["id"]
    cancel_event = threading.Event()
    message_timestamp = datetime.now()

    try:
        job = stream_job_registry.register(
            session_id=session_id,
            student_id="test",
            cancel_event=cancel_event,
            message_timestamp=message_timestamp,
        )
        job.publish(
            {
                "type": "progress",
                "phase": "generation",
                "message": "正在生成回答...",
                "stream_id": "restore-1",
            }
        )
        job.publish({"type": "delta", "delta": "已经生成的内容", "stream_id": "restore-1"})

        history_resp = client.get(f"/api/chat/history/{session_id}", headers={"x-test-student-id": "test"})
        assert history_resp.status_code == 200
        history = history_resp.json()
        assert history["active_stream"]["content"] == "已经生成的内容"
        assert history["active_stream"]["stream_id"] == "restore-1"
        assert history["active_stream"]["last_event_id"] == 2
        assert history["active_stream"]["progress"]["message"] == "正在生成回答..."

        cancel_resp = client.post(f"/api/chat/cancel/{session_id}", headers={"x-test-student-id": "test"})
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["cancelled"] is True
        assert cancel_event.is_set()
    finally:
        stream_job_registry.discard(session_id)


def test_resume_endpoint_starts_with_full_snapshot_and_replays_terminal_event():
    import threading
    from datetime import datetime

    from ds_course_agent.api.state import _chat_history, _sessions
    from ds_course_agent.api.stream_jobs import stream_job_registry

    _sessions.clear()
    _chat_history.clear()
    client = TestClient(app)
    session_resp = client.post(
        "/api/sessions",
        headers={"x-test-student-id": "test"},
        json={"title": "resume test"},
    )
    session_id = session_resp.json()["id"]
    timestamp = datetime.now()
    job = stream_job_registry.register(
        session_id=session_id,
        student_id="test",
        cancel_event=threading.Event(),
        message_timestamp=timestamp,
    )
    job.publish({"type": "delta", "delta": "刷新前", "stream_id": "resume-1"})
    job.publish({"type": "delta", "delta": "已经生成", "stream_id": "resume-1"})
    job.publish(
        {
            "type": "final",
            "stream_id": "resume-1",
            "message": {
                "role": "assistant",
                "content": "刷新前已经生成",
                "timestamp": timestamp.isoformat(),
                "generation_status": "completed",
            },
        }
    )

    response = client.get(f"/api/chat/resume/{session_id}", headers={"x-test-student-id": "test"})

    assert response.status_code == 200
    assert '"type": "snapshot"' in response.text
    assert '"content": "刷新前已经生成"' in response.text
    assert '"resuming": true' in response.text
    assert '"type": "final"' in response.text


def test_cancel_preserves_partial_answer_and_marks_it_stopped(monkeypatch):
    import threading
    import time

    from ds_course_agent.api.state import _chat_history, _sessions

    _sessions.clear()
    _chat_history.clear()
    first_delta_seen = threading.Event()
    release_generator = threading.Event()

    def fake_stream_chat_with_history(message: str, session_id: str, student_id: str):
        yield {
            "type": "progress",
            "phase": "retrieval_sources",
            "message": "已找到 1 个课程来源",
            "family": "learning",
            "intent": "concept_qa",
            "execution_mode": "grounded_generation",
            "tool": "course_rag_tool",
            "stream_id": "cancel-1",
            "details": {"sources": [{"reference": "《第1章》"}]},
        }
        yield {"type": "delta", "delta": "已经生成的部分", "stream_id": "cancel-1"}
        first_delta_seen.set()
        while not release_generator.is_set():
            time.sleep(0.01)
        yield {"type": "delta", "delta": "不应出现", "stream_id": "cancel-1"}

    import ds_course_agent.api.routers.chat as chat_module

    monkeypatch.setattr(chat_module, "stream_chat_with_history", fake_stream_chat_with_history)
    session_client = TestClient(app)
    session_resp = session_client.post(
        "/api/sessions",
        headers={"x-test-student-id": "test"},
        json={"title": "cancel partial"},
    )
    session_id = session_resp.json()["id"]
    response_holder = {}

    def send_request():
        response_holder["response"] = TestClient(app).post(
            "/api/chat/send/stream",
            headers={"x-test-student-id": "test"},
            json={"session_id": session_id, "message": "hello"},
        )

    request_thread = threading.Thread(target=send_request)
    request_thread.start()
    assert first_delta_seen.wait(timeout=2)

    cancel_resp = session_client.post(
        f"/api/chat/cancel/{session_id}",
        headers={"x-test-student-id": "test"},
    )
    assert cancel_resp.json()["cancelled"] is True
    release_generator.set()
    request_thread.join(timeout=3)
    assert not request_thread.is_alive()

    response = response_holder["response"]
    assert '"generation_status": "stopped"' in response.text
    history_resp = session_client.get(
        f"/api/chat/history/{session_id}",
        headers={"x-test-student-id": "test"},
    )
    assistant = history_resp.json()["messages"][-1]
    assert assistant["content"] == "已经生成的部分"
    assert assistant["family"] == "learning"
    assert assistant["intent"] == "concept_qa"
    assert assistant["execution_mode"] == "grounded_generation"
    assert "route" not in assistant
    assert assistant["sources"] == [{"reference": "《第1章》"}]
    assert assistant["metadata"]["used_retrieval"] is True
    assert assistant["generation_status"] == "stopped"
    assert assistant["generation_error"] is None


def test_continue_stream_replaces_stopped_message_without_visible_user_turn(monkeypatch):
    from datetime import datetime

    from ds_course_agent.api.routers.chat import _append_message_locked
    from ds_course_agent.api.schemas.chat import ChatMessage
    from ds_course_agent.api.state import _chat_history, _sessions

    _sessions.clear()
    _chat_history.clear()
    client = TestClient(app)
    session_resp = client.post(
        "/api/sessions",
        headers={"x-test-student-id": "test"},
        json={"title": "continue test"},
    )
    session_id = session_resp.json()["id"]
    stopped_at = datetime.now()
    _append_message_locked(session_id, ChatMessage(role="user", content="请详细解释"), save=False)
    _append_message_locked(
        session_id,
        ChatMessage(
            role="assistant",
            content="已有内容",
            timestamp=stopped_at,
            family="learning",
            intent="concept_qa",
            execution_mode="grounded_generation",
            sources=[{"reference": "《第1章》"}],
            generation_status="stopped",
            metadata={"used_retrieval": True},
        ),
    )

    def fake_continue(partial_content: str, session_id: str, student_id: str):
        assert partial_content == "已有内容"
        yield {"type": "progress", "phase": "generation", "message": "正在继续生成...", "stream_id": "continue-1"}
        yield {"type": "delta", "delta": "，后续内容", "stream_id": "continue-1"}
        yield {
            "type": "final",
            "content": "已有内容，后续内容",
            "stream_id": "continue-1",
            "used_retrieval": False,
            "sources": [],
        }

    import ds_course_agent.api.routers.chat as chat_module

    monkeypatch.setattr(chat_module, "stream_continue_with_history", fake_continue)
    response = client.post(
        "/api/chat/continue/stream",
        headers={"x-test-student-id": "test"},
        json={
            "session_id": session_id,
            "message_timestamp": stopped_at.isoformat(),
        },
    )

    assert response.status_code == 200
    assert '"type": "delta"' in response.text
    assert '"generation_status": "completed"' in response.text
    history_resp = client.get(f"/api/chat/history/{session_id}", headers={"x-test-student-id": "test"})
    messages = history_resp.json()["messages"]
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[-1]["content"] == "已有内容，后续内容"
    assert messages[-1]["family"] == "learning"
    assert messages[-1]["intent"] == "concept_qa"
    assert messages[-1]["execution_mode"] == "grounded_generation"
    assert "route" not in messages[-1]
    assert messages[-1]["sources"] == [{"reference": "《第1章》"}]
    assert messages[-1]["metadata"]["used_retrieval"] is True
    assert messages[-1]["generation_status"] == "completed"
