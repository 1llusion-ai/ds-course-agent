"""Authentication HTTP adapters, backed by one account and registration owner."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

import ds_course_agent.shared.config as config

from . import models, registration
from .contracts import AccountStatus, Role, User
from .deps import check_request_origin, get_current_user
from .service import create_session_token, hash_password, session_ttl_seconds, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=8, max_length=256)
    invite_code: str = Field(default="", max_length=256)

    @field_validator("username", "invite_code")
    @classmethod
    def normalize_text(cls, value: str, info) -> str:
        value = value.strip()
        if info.field_name == "username" and not value:
            raise ValueError("must not be blank")
        return value


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class AuthUserResponse(BaseModel):
    student_id: str
    display_name: str
    role: Role


def user_response(user: User) -> AuthUserResponse:
    return AuthUserResponse(student_id=user.student_id, display_name=user.display_name, role=user.role)


def set_session(response: Response, user: User) -> None:
    response.set_cookie(
        "session",
        create_session_token(user),
        max_age=session_ttl_seconds(),
        httponly=True,
        secure=bool(config.AUTH_COOKIE_SECURE),
        samesite="lax",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"


@router.get("/registration-policy")
async def public_registration_policy():
    policy = registration.get_policy()
    opened = registration.registration_open(policy)
    return {
        "mode": policy.mode if opened else "closed",
        "registration_open": opened,
        "invite_required": opened and policy.mode == "invite",
    }


@router.post("/login", response_model=AuthUserResponse)
async def login(data: LoginRequest, request: Request, response: Response):
    check_request_origin(request)
    user = models.get_user_by_username(data.username)
    if not user or user.status != AccountStatus.ACTIVE or not verify_password(data.password, user.password_hash):
        raise HTTPException(401, "用户名或密码错误")
    user = models.record_login(user)
    set_session(response, user)
    return user_response(user)


@router.post("/register", response_model=AuthUserResponse, status_code=201)
async def register(data: RegisterRequest, request: Request, response: Response):
    check_request_origin(request)
    user = registration.register_user(
        username=data.username, password_hash=hash_password(data.password), invite_code=data.invite_code
    )
    user = models.record_login(user)
    set_session(response, user)
    return user_response(user)


@router.post("/change-password", response_model=AuthUserResponse)
async def change_password(data: ChangePasswordRequest, response: Response, user: User = Depends(get_current_user)):
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(403, "当前密码不正确")
    if data.current_password == data.new_password:
        raise HTTPException(422, "新密码不能与当前密码相同")
    updated = models.update_user_password(
        username=user.username, password_hash=hash_password(data.new_password), expected_hash=user.password_hash
    )
    if updated is None:
        raise HTTPException(404, "用户不存在")
    set_session(response, updated)
    return user_response(updated)


@router.post("/logout")
async def logout(request: Request, response: Response):
    check_request_origin(request)
    response.delete_cookie("session", path="/")
    return {"ok": True}


@router.get("/me", response_model=AuthUserResponse)
async def me(response: Response, user: User = Depends(get_current_user)):
    response.headers["Cache-Control"] = "no-store"
    return user_response(user)
