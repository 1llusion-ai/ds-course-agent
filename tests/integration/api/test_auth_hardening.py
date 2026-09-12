"""Production authentication and admission failures must be explicit and bounded."""

from __future__ import annotations

import asyncio
import importlib
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from jose import jwt

import ds_course_agent.shared.config as config
from ds_course_agent.api.auth import models, service
from ds_course_agent.api.main import app, lifespan


@pytest.mark.parametrize("secret", ["", "short", " " * 48, "dev-insecure-auth-secret-change-me"])
def test_production_refuses_missing_or_development_signing_key(monkeypatch, secret):
    monkeypatch.setattr(config, "APP_ENV", "production")
    monkeypatch.setattr(config, "AUTH_SECRET_KEY", secret)

    async def startup() -> None:
        async with lifespan(app):
            pytest.fail("invalid configuration reached startup")

    # The repository's same-thread TestClient does not run lifespan events.
    with pytest.raises(ValueError, match="AUTH_SECRET_KEY"):
        asyncio.run(startup())


def test_production_sets_secure_cookie_despite_legacy_false_setting(monkeypatch):
    monkeypatch.setattr(config, "APP_ENV", "production")
    monkeypatch.setattr(config, "AUTH_SECRET_KEY", "test-only-signing-key-with-more-than-thirty-two-bytes")
    monkeypatch.setattr(config, "AUTH_COOKIE_SECURE", False)
    models.create_or_update_user(
        username="alice", password_hash=service.hash_password("secret"), student_id="alice", display_name="Alice"
    )
    with TestClient(app, base_url="https://testserver") as client:
        response = client.post("/api/auth/login", json={"username": "alice", "password": "secret"})
        assert response.status_code == 200
        cookie = response.headers["set-cookie"]
        assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
        assert client.get("/api/auth/me").status_code == 200


def test_development_fallback_cannot_verify_the_published_old_key(monkeypatch):
    monkeypatch.setattr(config, "AUTH_SECRET_KEY", "")
    token = service.create_session_token("alice", "Alice")
    assert service.decode_session_token(token)["student_id"] == "alice"
    forged = jwt.encode({"student_id": "alice"}, "dev-insecure-auth-secret-change-me", algorithm="HS256")
    with pytest.raises(service.AuthTokenError):
        service.decode_session_token(forged)


def test_login_rate_limit_precedes_password_verification(monkeypatch):
    auth_router = importlib.import_module("ds_course_agent.api.auth.router")

    monkeypatch.setattr(config, "AUTH_LOGIN_MAX_PER_ACCOUNT", 2)
    monkeypatch.setattr(models, "get_user_by_username", Mock(return_value={"password_hash": "unused"}))
    verify = Mock(return_value=False)
    monkeypatch.setattr(auth_router, "verify_password", verify)
    with TestClient(app) as client:
        for _ in range(2):
            assert client.post("/api/auth/login", json={"username": "alice", "password": "wrong"}).status_code == 401
        rejected = client.post("/api/auth/login", json={"username": "alice", "password": "wrong"})
    assert rejected.status_code == 429
    assert int(rejected.headers["retry-after"]) > 0
    assert verify.call_count == 2
