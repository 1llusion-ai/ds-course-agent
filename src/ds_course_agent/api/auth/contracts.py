"""Typed identities and registration contracts for authentication and administration."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Role(str, Enum):
    STUDENT = "student"
    OBSERVER = "observer"
    ADMIN = "admin"


class AccountStatus(str, Enum):
    ACTIVE = "active"
    DISABLED = "disabled"


class RegistrationMode(str, Enum):
    CLOSED = "closed"
    INVITE = "invite"
    OPEN = "open"


class AuthOperationError(Exception):
    """An expected authentication/administration rejection safe to show to clients."""

    def __init__(self, detail: str, status_code: int = 409) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class User:
    id: int
    username: str
    student_id: str
    display_name: str
    created_at: str
    updated_at: str
    role: Role
    status: AccountStatus
    last_login_at: str | None
    registration_source: str
    invitation_id: int | None
    password_hash: str = field(repr=False)
    session_version: int = field(repr=False)


@dataclass(frozen=True)
class RegistrationPolicy:
    mode: RegistrationMode
    max_users: int


@dataclass(frozen=True)
class Invitation:
    id: int
    name: str
    note: str
    code_hint: str
    expires_at: str | None
    max_uses: int
    used_count: int
    enabled: bool
    created_at: str


@dataclass(frozen=True)
class InvitationUse:
    user_id: int
    username: str
    display_name: str
    registered_at: str


@dataclass(frozen=True)
class AuditEntry:
    id: int
    actor: str
    action: str
    target: str
    created_at: str
    before: dict[str, object]
    after: dict[str, object]
