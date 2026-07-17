from fastapi.testclient import TestClient

from ds_course_agent.api.main import app


def test_auth_login_success_failure_and_me(monkeypatch, tmp_path):
    from ds_course_agent.api.auth import models
    from ds_course_agent.api.auth.service import hash_password

    db_path = tmp_path / "auth.db"
    monkeypatch.setattr("ds_course_agent.api.auth.models.config.AUTH_DB_PATH", str(db_path))
    monkeypatch.setattr("ds_course_agent.api.auth.service.config.AUTH_SECRET_KEY", "test-secret")
    models.init_db()
    models.create_or_update_user(
        username="alice",
        password_hash=hash_password("secret"),
        student_id="student_a",
        display_name="Alice",
    )

    with TestClient(app) as client:
        bad = client.post("/api/auth/login", json={"username": "alice", "password": "wrong"})
        assert bad.status_code == 401

        ok = client.post("/api/auth/login", json={"username": "alice", "password": "secret"})
        assert ok.status_code == 200
        assert ok.json() == {"student_id": "student_a", "display_name": "Alice"}
        assert "session" in ok.cookies

        me = client.get("/api/auth/me")
        assert me.status_code == 200
        assert me.json()["student_id"] == "student_a"

        logout = client.post("/api/auth/logout")
        assert logout.status_code == 200


def test_protected_endpoint_without_cookie_returns_401():
    from ds_course_agent.api.auth.deps import get_current_student_id

    app.dependency_overrides.pop(get_current_student_id, None)
    with TestClient(app) as client:
        response = client.get("/api/sessions")
    assert response.status_code == 401


def test_session_ownership_enforced_with_auth_override():
    with TestClient(app) as client:
        created = client.post(
            "/api/sessions",
            headers={"x-test-student-id": "owner"},
            json={"title": "私密会话", "student_id": "ignored"},
        )
        assert created.status_code == 200
        session_id = created.json()["id"]
        assert created.json()["student_id"] == "owner"

        forbidden = client.get(
            f"/api/sessions/{session_id}",
            headers={"x-test-student-id": "other"},
        )
        assert forbidden.status_code == 403

        hidden_list = client.get("/api/sessions", headers={"x-test-student-id": "other"})
        assert hidden_list.status_code == 200
        assert hidden_list.json()["sessions"] == []

        forbidden_chat = client.post(
            "/api/chat/send",
            headers={"x-test-student-id": "other"},
            json={"session_id": session_id, "message": "测试", "student_id": "owner"},
        )
        assert forbidden_chat.status_code == 403


def test_cookie_session_ownership_is_enforced(monkeypatch, tmp_path):
    from ds_course_agent.api.auth import models
    from ds_course_agent.api.auth.deps import get_current_student_id
    from ds_course_agent.api.auth.service import hash_password
    from ds_course_agent.api.state import _chat_history, _sessions

    db_path = tmp_path / "auth.db"
    monkeypatch.setattr("ds_course_agent.api.auth.models.config.AUTH_DB_PATH", str(db_path))
    monkeypatch.setattr("ds_course_agent.api.auth.service.config.AUTH_SECRET_KEY", "test-secret")
    models.init_db()
    models.create_or_update_user(
        username="alice",
        password_hash=hash_password("secret-a"),
        student_id="student_a",
        display_name="Alice",
    )
    models.create_or_update_user(
        username="bob",
        password_hash=hash_password("secret-b"),
        student_id="student_b",
        display_name="Bob",
    )
    _sessions.clear()
    _chat_history.clear()
    app.dependency_overrides.pop(get_current_student_id, None)

    with TestClient(app) as client:
        login_a = client.post("/api/auth/login", json={"username": "alice", "password": "secret-a"})
        assert login_a.status_code == 200
        created = client.post("/api/sessions", json={"title": "Alice session"})
        assert created.status_code == 200
        session_id = created.json()["id"]
        assert created.json()["student_id"] == "student_a"

        login_b = client.post("/api/auth/login", json={"username": "bob", "password": "secret-b"})
        assert login_b.status_code == 200
        forbidden = client.get(f"/api/sessions/{session_id}")
        assert forbidden.status_code == 403

        listed = client.get("/api/sessions")
        assert listed.status_code == 200
        assert listed.json()["sessions"] == []
