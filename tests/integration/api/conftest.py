import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from ds_course_agent.api.auth.deps import get_current_student_id
from ds_course_agent.api.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def isolated_backend_runtime(monkeypatch):
    """Keep backend API tests deterministic and independent from real LLM/RAG."""
    import ds_course_agent.api.routers.chat as chat_module
    import ds_course_agent.api.routers.profile as profile_module
    from ds_course_agent.api.state import _chat_history, _sessions

    _sessions.clear()
    _chat_history.clear()
    chat_module._title_gen_cache.clear()

    async def same_thread_run_in_threadpool(func, *args, **kwargs):
        return func(*args, **kwargs)

    async def fake_generate_session_title(question: str) -> str:
        return question[:10]

    def fake_chat_with_history(message: str, session_id: str, student_id: str):
        return {
            "content": f"测试回答：{message}",
            "used_retrieval": False,
            "sources": [],
            "family": "learning",
            "intent": "concept_qa",
            "execution_mode": "grounded_generation",
            "degraded": False,
            "query_trace": {},
        }

    def fake_stream_chat_with_history(message: str, session_id: str, student_id: str):
        yield {"type": "delta", "delta": "测试"}
        yield {
            "type": "final",
            "content": f"测试回答：{message}",
            "sources": [],
            "used_retrieval": False,
            "family": "learning",
            "intent": "concept_qa",
            "execution_mode": "grounded_generation",
            "degraded": False,
        }

    monkeypatch.setattr(chat_module, "_generate_session_title", fake_generate_session_title)
    monkeypatch.setattr(chat_module, "chat_with_history", fake_chat_with_history)
    monkeypatch.setattr(chat_module, "stream_chat_with_history", fake_stream_chat_with_history)
    monkeypatch.setattr(chat_module, "run_in_threadpool", same_thread_run_in_threadpool)
    monkeypatch.setattr(profile_module, "run_in_threadpool", same_thread_run_in_threadpool)

    async def test_current_student_id(request: Request) -> str:
        if request.headers.get("x-test-student-id"):
            return request.headers["x-test-student-id"]
        if request.query_params.get("student_id"):
            return str(request.query_params["student_id"])
        try:
            body = await request.json()
        except Exception:
            body = {}
        if isinstance(body, dict) and body.get("student_id"):
            return str(body["student_id"])
        return "student001"

    app.dependency_overrides[get_current_student_id] = test_current_student_id
    yield
    app.dependency_overrides.pop(get_current_student_id, None)
