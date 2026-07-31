from unittest.mock import patch

from fastapi.testclient import TestClient

from ds_course_agent.api.main import app

client = TestClient(app)


def setup_function():
    from ds_course_agent.api.state import _chat_history, _sessions

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


@patch("ds_course_agent.api.routers.chat.chat_with_history")
def test_send_message_omits_sources_when_agent_skips_retrieval(mock_chat_with_history):
    mock_chat_with_history.return_value = {
        "content": "你好！我是课程助教。",
        "used_retrieval": False,
        "sources": [],
        "family": "boundary",
        "intent": "smalltalk",
        "execution_mode": "static_response",
        "degraded": False,
        "query_trace": {},
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
    assert payload["message"]["family"] == "boundary"
    assert payload["message"]["intent"] == "smalltalk"
    assert payload["message"]["execution_mode"] == "static_response"
    assert "route" not in payload["message"]
    assert "route" not in (payload["message"]["metadata"] or {})


@patch("ds_course_agent.api.routers.chat.chat_with_history")
def test_send_message_keeps_sources_from_agent_retrieval(mock_chat_with_history):
    mock_chat_with_history.return_value = {
        "content": "PCA 通过协方差矩阵的特征分解找到主成分。",
        "used_retrieval": True,
        "sources": [{"reference": "《第7章 无监督学习算法》第123页"}],
        "family": "learning",
        "intent": "concept_qa",
        "execution_mode": "learning_answer",
        "degraded": False,
        "query_trace": {},
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
    assert payload["message"]["family"] == "learning"
    assert payload["message"]["intent"] == "concept_qa"
    assert payload["message"]["execution_mode"] == "learning_answer"

    history_response = client.get(f"/api/chat/history/{session_id}?student_id=student001")
    history_message = history_response.json()["messages"][-1]
    assert history_message["family"] == "learning"
    assert history_message["intent"] == "concept_qa"
    assert history_message["execution_mode"] == "learning_answer"
    assert "route" not in history_message
