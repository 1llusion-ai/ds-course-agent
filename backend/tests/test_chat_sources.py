from unittest.mock import patch

from fastapi.testclient import TestClient

from apps.api.app.main import app


client = TestClient(app)


def setup_function():
    from apps.api.app.state import _chat_history, _sessions

    _sessions.clear()
    _chat_history.clear()


def _create_session(student_id: str = "student001") -> str:
    response = client.post(
        "/api/sessions",
        json={
            "title": "测试会话",
            "student_id": student_id,
        },
    )
    assert response.status_code == 200
    return response.json()["id"]


@patch("apps.api.app.routers.chat.chat_with_history")
def test_send_message_omits_sources_when_agent_skips_retrieval(mock_chat_with_history):
    mock_chat_with_history.return_value = {
        "content": "你好！我是课程助教。",
        "used_retrieval": False,
        "sources": [],
    }

    session_id = _create_session()
    response = client.post(
        "/api/chat/send",
        json={
            "session_id": session_id,
            "message": "你好",
            "student_id": "student001",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["message"]["content"] == "你好！我是课程助教。"
    assert payload["message"]["sources"] is None


@patch("apps.api.app.routers.chat.chat_with_history")
def test_send_message_keeps_sources_from_agent_retrieval(mock_chat_with_history):
    mock_chat_with_history.return_value = {
        "content": "PCA 通过协方差矩阵的特征分解找到主成分。",
        "used_retrieval": True,
        "sources": [{"reference": "《第7章 无监督学习算法》第123页"}],
    }

    session_id = _create_session()
    response = client.post(
        "/api/chat/send",
        json={
            "session_id": session_id,
            "message": "PCA 的公式是什么？",
            "student_id": "student001",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["message"]["sources"] == [{"reference": "《第7章 无监督学习算法》第123页"}]
