"""Validated administration request contracts; public response fields are explicit projections."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ds_course_agent.api.auth.contracts import AccountStatus, Role


class AdminRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class CreateUserRequest(AdminRequest):
    username: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=8, max_length=256)
    role: Role = Role.STUDENT

    @field_validator("username", "display_name")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("不能为空")
        return value.strip()


class EditUserRequest(AdminRequest):
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    role: Role | None = None
    status: AccountStatus | None = None

    @field_validator("display_name")
    @classmethod
    def nonblank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("不能为空")
        return value.strip() if value is not None else None


class PasswordRequest(AdminRequest):
    password: str = Field(min_length=8, max_length=256)


class PolicyRequest(AdminRequest):
    mode: Literal["closed", "invite"]
    max_users: int = Field(ge=0, le=100000000)


class InvitationRequest(AdminRequest):
    name: str = Field(min_length=1, max_length=128)
    note: str = Field(default="", max_length=1000)
    expires_at: datetime | None = None
    max_uses: int = Field(default=0, ge=0, le=100000000)

    @field_validator("name")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("不能为空")
        return value.strip()

    @field_validator("expires_at")
    @classmethod
    def timezone_required(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            if value.tzinfo is None:
                raise ValueError("有效期必须包含时区")
            return value.astimezone(timezone.utc)
        return None


class EditInvitationRequest(AdminRequest):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    note: str | None = Field(default=None, max_length=1000)
    expires_at: datetime | None = None
    max_uses: int | None = Field(default=None, ge=0, le=100000000)
    enabled: bool | None = None

    @field_validator("name")
    @classmethod
    def nonblank(cls, value: str | None) -> str | None:
        return InvitationRequest.nonblank(value) if value is not None else None

    @field_validator("expires_at")
    @classmethod
    def timezone_required(cls, value: datetime | None) -> datetime | None:
        return InvitationRequest.timezone_required(value)
