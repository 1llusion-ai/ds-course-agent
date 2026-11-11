"""Administrative permissions, invitations, migration and real cookie lifecycle contracts."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from ds_course_agent.api.auth import models, registration
from ds_course_agent.api.auth.contracts import AuthOperationError, RegistrationMode, RegistrationPolicy, Role
from ds_course_agent.api.auth.database import connection
from ds_course_agent.api.auth.deps import get_current_student_id
from ds_course_agent.api.auth.service import hash_password
from ds_course_agent.api.main import app


@pytest.fixture
def accounts(monkeypatch, tmp_path):
    import ds_course_agent.shared.config as config

    monkeypatch.setattr(config, "AUTH_DB_PATH", str(tmp_path / "auth.db"))
    monkeypatch.setattr(config, "ASSESSMENT_DB_PATH", str(tmp_path / "assessments.db"))
    monkeypatch.setattr(config, "AUTH_SECRET_KEY", "test-admin-secret")
    monkeypatch.setattr(config, "APP_ENV", "test")
    monkeypatch.setattr(config, "AUTH_COOKIE_SECURE", False)
    app.dependency_overrides.pop(get_current_student_id, None)
    password = hash_password("test-password")
    root = models.create_or_update_user(
        username="root", student_id="root", display_name="管理员", password_hash=password
    )
    root = models.bootstrap_admin(root.username)
    student = models.create_managed_user(
        actor_id=root.id, username="student", display_name="学生", password_hash=password, role=Role.STUDENT
    )
    observer = models.create_managed_user(
        actor_id=root.id, username="observer", display_name="观察者", password_hash=password, role=Role.OBSERVER
    )
    return root, student, observer


def login(name="root"):
    client = TestClient(app)
    result = client.post("/api/auth/login", json={"username": name, "password": "test-password"})
    assert result.status_code == 200, result.text
    return client


def test_role_matrix_and_no_secret_projection(accounts):
    assert TestClient(app).get("/api/admin/users").status_code == 401
    student = login("student")
    observer = login("observer")
    admin = login()
    for client in (student, observer):
        for path in ("users", "registration-policy", "invitations", "audit"):
            assert client.get("/api/admin/" + path).status_code == 403
        assert (
            client.post(
                "/api/admin/users",
                json={"username": "bad", "display_name": "bad", "password": "test-password", "role": "admin"},
            ).status_code
            == 403
        )
    assert student.get("/api/admin/statistics").status_code == 403
    assert student.get("/api/admin/statistics/export").status_code == 403
    assert observer.get("/api/admin/statistics").status_code == 200
    assert observer.get("/api/admin/statistics/export").status_code == 200
    response = admin.get("/api/admin/users", params={"q": "student"})
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.headers["cache-control"] == "no-store"
    assert not any(secret in response.text for secret in ("password_hash", "session_version", "$2b$"))
    assert admin.get("/api/admin/users", params={"page": 0}).status_code == 422
    assert admin.get("/api/admin/statistics", params={"start": "2020-01-01", "end": "2026-01-01"}).status_code == 422


def test_overview_signals_are_admin_only(accounts):
    assert TestClient(app).get("/api/admin/signals").status_code == 401
    student, observer = login("student"), login("observer")
    for client in (student, observer):
        assert client.get("/api/admin/signals").status_code == 403
    admin = login()
    payload = admin.get("/api/admin/signals").json()
    assert set(payload) == {"capacity", "invitations", "answers"}
    assert payload["capacity"] == {"max_users": 0, "total_users": 3, "remaining": None}
    assert payload["invitations"] == {"total": 0, "expiring": 0, "exhausted": 0}


def test_account_changes_revoke_old_sessions_and_protect_last_admin(accounts):
    root, student, _ = accounts
    admin = login()
    user = login("student")
    assert admin.patch(f"/api/admin/users/{root.id}", json={"role": "student"}).status_code == 409
    assert admin.patch(f"/api/admin/users/{root.id}", json={"status": "disabled"}).status_code == 409
    assert admin.patch(f"/api/admin/users/{student.id}", json={"status": "disabled"}).status_code == 200
    assert user.get("/api/auth/me").status_code == 401
    assert user.get("/api/sessions").status_code == 401
    assert user.post("/api/auth/login", json={"username": "student", "password": "test-password"}).status_code == 401
    assert admin.patch(f"/api/admin/users/{student.id}", json={"status": "active"}).status_code == 200
    assert user.get("/api/auth/me").status_code == 401
    user = login("student")
    assert admin.patch(f"/api/admin/users/{student.id}", json={"role": "observer"}).status_code == 200
    assert user.get("/api/admin/statistics").status_code == 401
    user = login("student")
    assert user.get("/api/admin/statistics").status_code == 200
    assert admin.post(f"/api/admin/users/{student.id}/revoke-sessions").status_code == 200
    assert user.get("/api/auth/me").status_code == 401
    user = login("student")
    assert (
        admin.post(f"/api/admin/users/{student.id}/reset-password", json={"password": "changed-password"}).status_code
        == 200
    )
    assert user.get("/api/auth/me").status_code == 401
    assert user.post("/api/auth/login", json={"username": "student", "password": "test-password"}).status_code == 401
    assert user.post("/api/auth/login", json={"username": "student", "password": "changed-password"}).status_code == 200
    audit = admin.get("/api/admin/audit").text
    assert "changed-password" not in audit and "test-password" not in audit
    assert "account.password_reset" in audit and "account.update" in audit


def test_self_password_change_keeps_current_browser_only(accounts):
    current, other = login("student"), login("student")
    response = current.post(
        "/api/auth/change-password", json={"current_password": "test-password", "new_password": "another-password"}
    )
    assert response.status_code == 200
    assert current.get("/api/auth/me").status_code == 200
    assert other.get("/api/auth/me").status_code == 401


def test_invitation_lifecycle_and_atomic_failed_registration(accounts):
    admin = login()
    assert admin.put("/api/admin/registration-policy", json={"mode": "invite", "max_users": 5}).status_code == 200
    response = admin.post("/api/admin/invitations", json={"name": "一班", "note": "2026", "max_uses": 1})
    assert response.status_code == 201
    code = response.json()["code"]
    invitation_id = response.json()["invitation"]["id"]
    assert code not in admin.get("/api/admin/invitations").text
    assert code not in admin.get("/api/admin/audit").text
    client = TestClient(app)
    assert client.get("/api/auth/registration-policy").json()["invite_required"] is True
    duplicate = client.post(
        "/api/auth/register", json={"username": "student", "password": "test-password", "invite_code": code}
    )
    assert duplicate.status_code == 409
    assert admin.get("/api/admin/invitations").json()["items"][0]["used_count"] == 0
    privilege = client.post(
        "/api/auth/register",
        json={"username": "new", "password": "test-password", "invite_code": code, "role": "admin"},
    )
    assert privilege.status_code == 422
    created = client.post(
        "/api/auth/register", json={"username": "new", "password": "test-password", "invite_code": code}
    )
    assert created.status_code == 201 and created.json()["role"] == "student"
    used = admin.get(f"/api/admin/invitations/{invitation_id}/uses").json()
    assert used["total"] == 1 and used["items"][0]["username"] == "new"
    assert (
        client.post(
            "/api/auth/register", json={"username": "next", "password": "test-password", "invite_code": code}
        ).status_code
        == 403
    )
    assert (
        admin.patch(f"/api/admin/invitations/{invitation_id}", json={"max_uses": 2, "enabled": False}).status_code
        == 200
    )
    assert client.get("/api/auth/me").status_code == 200
    assert (
        client.post(
            "/api/auth/register", json={"username": "next", "password": "test-password", "invite_code": code}
        ).status_code
        == 403
    )
    expired = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    assert (
        admin.patch(
            f"/api/admin/invitations/{invitation_id}", json={"enabled": True, "expires_at": expired}
        ).status_code
        == 200
    )
    assert admin.get("/api/admin/invitations").json()["items"][0]["status"] == "expired"
    assert (
        client.post(
            "/api/auth/register", json={"username": "next", "password": "test-password", "invite_code": code}
        ).status_code
        == 403
    )
    assert admin.patch(f"/api/admin/invitations/{invitation_id}", json={"expires_at": None}).status_code == 200
    assert (
        client.post(
            "/api/auth/register", json={"username": "next", "password": "test-password", "invite_code": code}
        ).status_code
        == 201
    )
    assert admin.put("/api/admin/registration-policy", json={"mode": "closed", "max_users": 5}).status_code == 200
    assert client.get("/api/auth/registration-policy").json()["registration_open"] is False
    assert (
        client.post(
            "/api/auth/register", json={"username": "closed", "password": "test-password", "invite_code": code}
        ).status_code
        == 503
    )


@pytest.mark.parametrize("invitation_limit,account_limit", [(1, 0), (0, 4)])
def test_parallel_registration_never_exceeds_limit(accounts, invitation_limit, account_limit):
    root, _, _ = accounts
    registration.update_policy(actor_id=root.id, policy=RegistrationPolicy(RegistrationMode.INVITE, account_limit))
    invitation, code = registration.create_invitation(
        actor_id=root.id, name="parallel", note="", expires_at=None, max_uses=invitation_limit
    )
    password = hash_password("test-password")

    def register(index):
        try:
            return registration.register_user(username=f"parallel-{index}", password_hash=password, invite_code=code)
        except AuthOperationError:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(register, range(8)))
    assert sum(result is not None for result in results) == 1
    assert registration.list_uses(invitation.id)[1] == 1
    assert registration.list_invitations()[0][0].used_count == 1


def test_origin_check_rejects_foreign_cookie_write(accounts):
    admin = login()
    result = admin.put(
        "/api/admin/registration-policy",
        json={"mode": "invite", "max_users": 0},
        headers={"Origin": "https://attacker.invalid"},
    )
    assert result.status_code == 403
    assert registration.get_policy().mode == RegistrationMode.CLOSED


def test_admin_failure_rolls_back_if_audit_write_fails(accounts, monkeypatch):
    root, student, _ = accounts

    def fail(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(models, "record_audit", fail)
    with pytest.raises(RuntimeError):
        models.edit_user(actor_id=root.id, user_id=student.id, display_name="changed")
    assert models.get_user(student.id).display_name == "学生"
