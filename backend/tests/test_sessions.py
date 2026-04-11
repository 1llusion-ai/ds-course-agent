from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_create_session():
    response = client.post(
        "/api/sessions",
        json={"title": "测试会话", "student_id": "student_001"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "测试会话"
    assert "id" in data
    assert data["student_id"] == "student_001"


def test_list_sessions():
    client.post("/api/sessions", json={"title": "会话1", "student_id": "student_001"})
    client.post("/api/sessions", json={"title": "会话2", "student_id": "student_001"})

    response = client.get("/api/sessions?student_id=student_001")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 2
    assert len(data["sessions"]) >= 2


def test_get_session():
    create_resp = client.post(
        "/api/sessions",
        json={"title": "获取测试会话", "student_id": "student_002"},
    )
    session_id = create_resp.json()["id"]

    get_resp = client.get(f"/api/sessions/{session_id}?student_id=student_002")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["id"] == session_id
    assert data["title"] == "获取测试会话"


def test_get_session_not_found():
    response = client.get("/api/sessions/nonexistent-id")
    assert response.status_code == 404
    assert "不存在" in response.json()["detail"]


def test_delete_session():
    create_resp = client.post("/api/sessions", json={"title": "待删除"})
    session_id = create_resp.json()["id"]

    delete_resp = client.delete(f"/api/sessions/{session_id}")
    assert delete_resp.status_code == 200
    assert "已删除" in delete_resp.json()["message"]

    get_resp = client.get(f"/api/sessions/{session_id}")
    assert get_resp.status_code == 404


def test_delete_session_not_found():
    response = client.delete("/api/sessions/nonexistent-id")
    assert response.status_code == 404


def test_update_session():
    create_resp = client.post(
        "/api/sessions",
        json={"title": "原标题", "student_id": "student_003"},
    )
    session_id = create_resp.json()["id"]

    patch_resp = client.patch(
        f"/api/sessions/{session_id}",
        json={"title": "更新后的标题"},
    )
    assert patch_resp.status_code == 200
    data = patch_resp.json()
    assert data["title"] == "更新后的标题"


def test_update_session_not_found():
    response = client.patch("/api/sessions/nonexistent-id", json={"title": "新标题"})
    assert response.status_code == 404


def test_list_sessions_filter_by_student():
    client.post("/api/sessions", json={"title": "学生A会话", "student_id": "student_A"})
    client.post("/api/sessions", json={"title": "学生B会话", "student_id": "student_B"})

    response = client.get("/api/sessions?student_id=student_A")
    assert response.status_code == 200
    data = response.json()
    for session in data["sessions"]:
        assert session["student_id"] == "student_A"


def test_restore_legacy_session_file(monkeypatch, tmp_path):
    from app import state as state_module

    legacy_session_id = "11111111-2222-3333-4444-555555555555"
    legacy_file = tmp_path / legacy_session_id
    legacy_file.write_text(
        json.dumps(
            [
                {"type": "human", "data": {"content": "旧会话里的第一条问题"}},
                {"type": "ai", "data": {"content": "旧会话里的回答"}},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(state_module, "STATE_FILE", tmp_path / "backend_state.json")
    monkeypatch.setattr(state_module, "_sessions", {})
    monkeypatch.setattr(state_module, "_chat_history", {})
    monkeypatch.setattr(state_module, "_deleted_session_ids", set())

    assert state_module._restore_sessions_from_legacy_files() is True
    assert legacy_session_id in state_module._chat_history
    assert legacy_session_id in state_module._sessions
    assert state_module._sessions[legacy_session_id]["title"] == "旧会话里的第一条问题"
    assert state_module._sessions[legacy_session_id]["student_id"] == "default_student"


def test_restore_legacy_session_file_skips_deleted_sessions(monkeypatch, tmp_path):
    from app import state as state_module

    legacy_session_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    legacy_file = tmp_path / legacy_session_id
    legacy_file.write_text(
        json.dumps(
            [{"type": "human", "data": {"content": "应该被跳过的旧会话"}}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(state_module, "STATE_FILE", tmp_path / "backend_state.json")
    monkeypatch.setattr(state_module, "_sessions", {})
    monkeypatch.setattr(state_module, "_chat_history", {})
    monkeypatch.setattr(state_module, "_deleted_session_ids", {legacy_session_id})

    assert state_module._restore_sessions_from_legacy_files() is False
    assert legacy_session_id not in state_module._chat_history
    assert legacy_session_id not in state_module._sessions


def test_purge_session_removes_legacy_file_and_records_tombstone(monkeypatch, tmp_path):
    from app import state as state_module

    session_id = "99999999-8888-7777-6666-555555555555"
    legacy_file = tmp_path / session_id
    legacy_file.write_text("[]", encoding="utf-8")

    monkeypatch.setattr(state_module, "STATE_FILE", tmp_path / "backend_state.json")
    monkeypatch.setattr(
        state_module,
        "_sessions",
        {
            session_id: {
                "title": "待清理会话",
                "student_id": "default_student",
                "created_at": "2026-04-11T10:00:00",
                "updated_at": "2026-04-11T10:00:00",
                "message_count": 2,
            }
        },
    )
    monkeypatch.setattr(state_module, "_chat_history", {session_id: [{"role": "user", "content": "hello"}]})
    monkeypatch.setattr(state_module, "_deleted_session_ids", set())

    assert state_module.purge_session(session_id) is True
    assert session_id not in state_module._sessions
    assert session_id not in state_module._chat_history
    assert session_id in state_module._deleted_session_ids
    assert not legacy_file.exists()
