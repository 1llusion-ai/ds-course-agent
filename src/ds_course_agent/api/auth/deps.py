"""Database-checked cookie authentication and centralized role authorization."""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request, status

import ds_course_agent.shared.config as config

from .contracts import AccountStatus, AuthOperationError, Role, User
from .models import get_user
from .service import AuthTokenError, decode_session_token


def check_request_origin(request: Request) -> None:
    """Reject cross-origin cookie writes outside the configured browser origins."""
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    origin = request.headers.get("origin")
    if request.headers.get("sec-fetch-site") == "cross-site" and not origin:
        raise HTTPException(403, "请求来源不受信任")
    if origin:
        allowed = {value.strip().rstrip("/") for value in config.CORS_ALLOW_ORIGINS.split(",") if value.strip()}
        own = urlsplit(str(request.base_url))
        allowed.add(f"{own.scheme}://{own.netloc}")
        if origin.rstrip("/") not in allowed:
            raise HTTPException(403, "请求来源不受信任")


async def get_current_user(request: Request) -> User:
    token = request.cookies.get("session")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    try:
        claims = decode_session_token(token)
        user = get_user(int(claims["user_id"]))
        if user.status != AccountStatus.ACTIVE or user.session_version != claims.get("session_version"):
            raise AuthTokenError("revoked session")
        if user.student_id != claims.get("student_id"):
            raise AuthTokenError("identity mismatch")
    except (AuthTokenError, AuthOperationError, KeyError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效") from exc
    check_request_origin(request)
    return user


async def get_current_student_id(request: Request) -> str:
    return (await get_current_user(request)).student_id


async def require_administrator(user: User = Depends(get_current_user)) -> User:
    if user.role != Role.ADMIN:
        raise HTTPException(403, "需要管理员权限")
    return user


async def require_statistics_reader(user: User = Depends(get_current_user)) -> User:
    if user.role not in {Role.ADMIN, Role.OBSERVER}:
        raise HTTPException(403, "需要统计查看权限")
    return user
