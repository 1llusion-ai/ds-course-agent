"""Authentication service functions: password hashing and signed sessions."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any, ParamSpec, TypeVar

import bcrypt
from anyio import CapacityLimiter, WouldBlock, to_thread
from jose import JWTError, jwt

import ds_course_agent.shared.config as config
from ds_course_agent.shared.config.production import production_auth_secret_is_valid

from . import models, registration
from .contracts import AccountStatus, AuthOperationError, User

logger = logging.getLogger(__name__)

_ALGORITHM = "HS256"
_DEV_SECRET = "dev-insecure-auth-secret-change-me"
_warned_empty_secret = False
_password_workers = CapacityLimiter(4)
_password_requests = CapacityLimiter(64)
_Args = ParamSpec("_Args")
_Result = TypeVar("_Result")


class AuthTokenError(ValueError):
    """Raised when a session token cannot be decoded or validated."""


def _secret_key() -> str:
    global _warned_empty_secret
    secret = str(getattr(config, "AUTH_SECRET_KEY", "") or "")
    if str(getattr(config, "APP_ENV", "development")) == "production" and not production_auth_secret_is_valid(secret):
        raise RuntimeError("AUTH_SECRET_KEY must be a strong secret in production")
    if secret:
        return secret
    if not _warned_empty_secret:
        logger.warning("AUTH_SECRET_KEY is empty; using an insecure development fallback")
        _warned_empty_secret = True
    return _DEV_SECRET


def session_ttl_seconds() -> int:
    return max(1, int(getattr(config, "AUTH_SESSION_TTL_HOURS", 12) or 12) * 3600)


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("password must not be empty")
    if len(password.encode("utf-8")) > 72:
        raise AuthOperationError("密码的 UTF-8 长度不能超过 72 字节", 422)
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    if not password or not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


async def run_password_work(operation: Callable[_Args, _Result], *args: _Args.args, **kwargs: _Args.kwargs) -> _Result:
    """Bound queued password requests and keep bcrypt and auth writes off the API loop."""
    try:
        _password_requests.acquire_nowait()
    except WouldBlock as exc:
        raise AuthOperationError("认证请求较多，请稍后重试。", 429) from exc
    try:
        return await to_thread.run_sync(lambda: operation(*args, **kwargs), limiter=_password_workers)
    finally:
        _password_requests.release()


def authenticate(username: str, password: str) -> User:
    user = models.get_user_by_username(username)
    if not user or user.status != AccountStatus.ACTIVE or not verify_password(password, user.password_hash):
        raise AuthOperationError("用户名或密码错误", 401)
    return models.record_login(user)


def register_account(username: str, password: str, invite_code: str) -> User:
    user = registration.register_user(username=username, password_hash=hash_password(password), invite_code=invite_code)
    return models.record_login(user)


def change_account_password(user: User, current_password: str, new_password: str) -> User:
    if not verify_password(current_password, user.password_hash):
        raise AuthOperationError("当前密码不正确", 403)
    if current_password == new_password:
        raise AuthOperationError("新密码不能与当前密码相同", 422)
    updated = models.update_user_password(
        username=user.username, password_hash=hash_password(new_password), expected_hash=user.password_hash
    )
    if updated is None:
        raise AuthOperationError("用户不存在", 404)
    return updated


def create_session_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(seconds=session_ttl_seconds())
    payload = {
        "sub": str(user.id),
        "student_id": user.student_id,
        "display_name": user.display_name,
        "user_id": user.id,
        "session_version": user.session_version,
        "iat": now,
        "exp": exp,
    }
    return jwt.encode(payload, _secret_key(), algorithm=_ALGORITHM)


def decode_session_token(token: str) -> dict[str, Any]:
    try:
        claims = jwt.decode(token, _secret_key(), algorithms=[_ALGORITHM])
    except JWTError as exc:
        raise AuthTokenError("invalid session token") from exc

    student_id = str(claims.get("student_id") or claims.get("sub") or "").strip()
    if not student_id:
        raise AuthTokenError("session token missing student_id")
    claims["student_id"] = student_id
    claims.setdefault("display_name", student_id)
    return claims
