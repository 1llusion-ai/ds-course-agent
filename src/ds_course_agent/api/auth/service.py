"""Authentication service functions: password hashing and signed sessions."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from jose import JWTError, jwt

import ds_course_agent.shared.config as config

from .contracts import AuthOperationError, User

logger = logging.getLogger(__name__)

_ALGORITHM = "HS256"
_DEV_SECRET = "dev-insecure-auth-secret-change-me"
_warned_empty_secret = False


class AuthTokenError(ValueError):
    """Raised when a session token cannot be decoded or validated."""


def _secret_key() -> str:
    global _warned_empty_secret
    secret = str(getattr(config, "AUTH_SECRET_KEY", "") or "")
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
