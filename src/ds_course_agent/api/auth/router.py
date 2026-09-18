"""Authentication API routes."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator

import ds_course_agent.shared.config as config

from . import models
from .deps import get_current_user
from .service import create_session_token, hash_password, session_ttl_seconds, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=8, max_length=256)

    @field_validator("username")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized


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


@router.post("/register", response_model=AuthUserResponse, status_code=status.HTTP_201_CREATED)
async def register(data: RegisterRequest, response: Response):
    username = data.username.strip()
    try:
        user = models.create_user(
            username=username,
            password_hash=hash_password(data.password),
            student_id=username,
            display_name=username,
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该用户名已存在") from exc

    student_id = str(user["student_id"])
    registered_display_name = str(user.get("display_name") or student_id)
    token = create_session_token(student_id, registered_display_name)
    response.set_cookie(
        "session",
        token,
        max_age=session_ttl_seconds(),
        httponly=True,
        secure=bool(config.AUTH_COOKIE_SECURE),
        samesite="lax",
        path="/",
    )
    return AuthUserResponse(student_id=student_id, display_name=registered_display_name)


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
