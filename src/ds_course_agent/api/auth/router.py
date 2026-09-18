"""Authentication API routes."""

from __future__ import annotations

import secrets
import sqlite3
from datetime import datetime, timezone

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
    invite_code: str = Field(default="", max_length=256)

    @field_validator("username")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    @field_validator("invite_code")
    @classmethod
    def normalize_invite_code(cls, value: str) -> str:
        return value.strip()


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class AuthUserResponse(BaseModel):
    student_id: str
    display_name: str


_INVITE_REQUIRED_MESSAGE = "需要有效的班级邀请码才能注册。"
_REGISTRATION_UNAVAILABLE_MESSAGE = "当前暂未开放注册，请联系管理员。"
_REGISTRATION_CAPACITY_MESSAGE = "本班级注册人数已达到上限，请联系管理员。"


def _invite_registration_allowed(invite_code: str) -> bool:
    mode = str(getattr(config, "AUTH_REGISTRATION_MODE", "open") or "open").strip().lower()
    app_env = str(getattr(config, "APP_ENV", "development") or "development").strip().lower()
    if mode == "open":
        return app_env in {"development", "test"}
    if mode != "invite":
        return False

    configured_code = str(getattr(config, "AUTH_INVITE_CODE", "") or "").strip()
    if not configured_code:
        return False
    expires_at = getattr(config, "AUTH_INVITE_EXPIRES_AT", None)
    if expires_at:
        if isinstance(expires_at, str):
            try:
                expires_at = datetime.fromisoformat(expires_at)
            except ValueError:
                return False
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) >= expires_at:
            return False
    return bool(invite_code) and secrets.compare_digest(invite_code, configured_code)


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
    mode = str(getattr(config, "AUTH_REGISTRATION_MODE", "open") or "open").strip().lower()
    if mode == "invite":
        if not _invite_registration_allowed(data.invite_code):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_INVITE_REQUIRED_MESSAGE)
    elif mode not in {"open"} or str(getattr(config, "APP_ENV", "development")).lower() == "production":
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=_REGISTRATION_UNAVAILABLE_MESSAGE)

    username = data.username.strip()
    max_users = 0
    if mode == "invite":
        try:
            max_users = int(getattr(config, "AUTH_MAX_USERS", 0) or 0)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=_REGISTRATION_UNAVAILABLE_MESSAGE,
            ) from None
        if max_users < 0:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=_REGISTRATION_UNAVAILABLE_MESSAGE
            )
    try:
        user = models.create_user(
            username=username,
            password_hash=hash_password(data.password),
            student_id=username,
            display_name=username,
            max_users=max_users,
        )
    except models.UserCapacityReached as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_REGISTRATION_CAPACITY_MESSAGE) from exc
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


@router.post("/change-password", response_model=AuthUserResponse)
async def change_password(data: ChangePasswordRequest, claims: dict = Depends(get_current_user)):
    user = models.get_user_by_student_id(str(claims["student_id"]))
    if not user or not verify_password(data.current_password, str(user.get("password_hash") or "")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前密码不正确")
    if data.current_password == data.new_password:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="新密码不能与当前密码相同")

    updated = models.update_user_password(
        username=str(user["username"]),
        password_hash=hash_password(data.new_password),
    )
    if updated is None:  # pragma: no cover - account deletion race is exceptional
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    return AuthUserResponse(
        student_id=str(updated["student_id"]),
        display_name=str(updated.get("display_name") or updated["student_id"]),
    )


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
