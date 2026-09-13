from __future__ import annotations

from fastapi.testclient import TestClient

from ds_course_agent.api.main import app

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
        headers={"x-test-student-id": "student_003"},
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
