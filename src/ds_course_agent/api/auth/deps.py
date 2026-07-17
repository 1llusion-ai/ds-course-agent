"""FastAPI dependencies for cookie session authentication."""

from __future__ import annotations

from fastapi import HTTPException, Request, status

from .service import AuthTokenError, decode_session_token


async def get_current_user(request: Request) -> dict:
    token = request.cookies.get("session")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    try:
        return decode_session_token(token)
    except AuthTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效") from exc


async def get_current_student_id(request: Request) -> str:
    return str((await get_current_user(request))["student_id"])
