import pytest
from fastapi.testclient import TestClient
from apps.api.app.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def isolated_backend_runtime(monkeypatch):
    """Keep backend API tests deterministic and independent from real LLM/RAG."""
    from apps.api.app.state import _chat_history, _sessions
    import apps.api.app.routers.chat as chat_module

    _sessions.clear()
    _chat_history.clear()
    chat_module._title_gen_cache.clear()

    async def fake_generate_session_title(question: str) -> str:
        return question[:10]

    def fake_chat_with_history(message: str, session_id: str, student_id: str):
        return {
            "content": f"测试回答：{message}",
            "used_retrieval": False,
            "sources": [],
        }

    def fake_stream_chat_with_history(message: str, session_id: str, student_id: str):
        yield {"type": "delta", "delta": "测试"}
        yield {"type": "final", "content": f"测试回答：{message}", "sources": []}

    monkeypatch.setattr(chat_module, "_generate_session_title", fake_generate_session_title)
    monkeypatch.setattr(chat_module, "chat_with_history", fake_chat_with_history)
    monkeypatch.setattr(chat_module, "stream_chat_with_history", fake_stream_chat_with_history)
