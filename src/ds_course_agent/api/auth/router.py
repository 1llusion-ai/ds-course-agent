"""Authentication API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

import ds_course_agent.shared.config as config

from . import models
from .deps import get_current_user
from .service import create_session_token, session_ttl_seconds, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class AuthUserResponse(BaseModel):
    student_id: str
    display_name: str


@router.post("/login", response_model=AuthUserResponse)
async def login(data: LoginRequest, response: Response):
    user = models.get_user_by_username(data.username)
    if not user or not verify_password(data.password, str(user.get("password_hash") or "")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")

    student_id = str(user["student_id"])
    display_name = str(user.get("display_name") or student_id)
    token = create_session_token(student_id, display_name)
    response.set_cookie(
        "session",
        token,
        max_age=session_ttl_seconds(),
        httponly=True,
        secure=bool(config.AUTH_COOKIE_SECURE),
        samesite="lax",
        path="/",
    )
    return AuthUserResponse(student_id=student_id, display_name=display_name)


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("session", path="/")
    return {"ok": True}


@router.get("/me", response_model=AuthUserResponse)
async def me(claims: dict = Depends(get_current_user)):
    student_id = str(claims["student_id"])
    return AuthUserResponse(
        student_id=student_id,
        display_name=str(claims.get("display_name") or student_id),
    )
