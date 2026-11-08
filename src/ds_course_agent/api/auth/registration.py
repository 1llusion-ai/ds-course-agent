"""Invitation lifecycle and atomic registration quota enforcement."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone

import ds_course_agent.shared.config as config

from .audit import record_audit
from .contracts import AuthOperationError, Invitation, InvitationUse, RegistrationMode, RegistrationPolicy, User
from .database import connection, now_iso
from .models import insert_user, require_admin


def parse_time(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result


def code_digest(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def invitation_from_row(row: sqlite3.Row) -> Invitation:
    return Invitation(
        **{key: row[key] for key in Invitation.__dataclass_fields__ if key != "enabled"}, enabled=bool(row["enabled"])
    )


def invitation_status(invitation: Invitation) -> str:
    if not invitation.enabled:
        return "disabled"
    if invitation.expires_at and parse_time(invitation.expires_at) <= datetime.now(timezone.utc):
        return "expired"
    if invitation.max_uses and invitation.used_count >= invitation.max_uses:
        return "exhausted"
    return "active"


def get_policy() -> RegistrationPolicy:
    with connection() as conn:
        row = conn.execute("SELECT * FROM registration_policy WHERE id=1").fetchone()
        return RegistrationPolicy(RegistrationMode(row["mode"]), row["max_users"])


def registration_open(policy: RegistrationPolicy) -> bool:
    return policy.mode == RegistrationMode.INVITE or (
        policy.mode == RegistrationMode.OPEN and config.APP_ENV in {"development", "test"}
    )


def update_policy(*, actor_id: int, policy: RegistrationPolicy) -> RegistrationPolicy:
    if policy.max_users < 0 or policy.mode not in {RegistrationMode.CLOSED, RegistrationMode.INVITE}:
        raise AuthOperationError("注册模式或容量无效", 422)
    with connection(write=True) as conn:
        actor = require_admin(conn, actor_id)
        old = conn.execute("SELECT mode,max_users FROM registration_policy WHERE id=1").fetchone()
        conn.execute(
            "UPDATE registration_policy SET mode=?,max_users=?,legacy_imported=1 WHERE id=1",
            (policy.mode.value, policy.max_users),
        )
        record_audit(
            conn,
            actor=actor.username,
            action="registration.update",
            target="registration",
            before=dict(old),
            after=asdict(policy),
        )
    return policy


def create_invitation(
    *, actor_id: int, name: str, note: str, expires_at: str | None, max_uses: int
) -> tuple[Invitation, str]:
    code = secrets.token_urlsafe(24)
    with connection(write=True) as conn:
        actor = require_admin(conn, actor_id)
        invitation = insert_invitation(conn, code=code, name=name, note=note, expires_at=expires_at, max_uses=max_uses)
        record_audit(
            conn, actor=actor.username, action="invitation.create", target=str(invitation.id), after=asdict(invitation)
        )
    return invitation, code


def insert_invitation(
    conn: sqlite3.Connection, *, code: str, name: str, note: str, expires_at: str | None, max_uses: int
) -> Invitation:
    if max_uses < 0:
        raise AuthOperationError("使用次数不能小于零", 422)
    cursor = conn.execute(
        """INSERT INTO invitations(name,note,code_digest,code_hint,expires_at,max_uses,created_at)
           VALUES(?,?,?,?,?,?,?)""",
        (
            name,
            note,
            code_digest(code),
            "••••" + code[-4:] if len(code) >= 12 else "••••",
            expires_at,
            max_uses,
            now_iso(),
        ),
    )
    return require_invitation(conn, int(cursor.lastrowid))


def require_invitation(conn: sqlite3.Connection, invitation_id: int) -> Invitation:
    row = conn.execute("SELECT * FROM invitations WHERE id=?", (invitation_id,)).fetchone()
    if row is None:
        raise AuthOperationError("邀请码不存在", 404)
    return invitation_from_row(row)


def list_invitations(*, page: int = 1, page_size: int = 20) -> tuple[tuple[Invitation, ...], int]:
    with connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM invitations").fetchone()[0]
        rows = conn.execute(
            "SELECT * FROM invitations ORDER BY id DESC LIMIT ? OFFSET ?", (page_size, (page - 1) * page_size)
        ).fetchall()
    return tuple(invitation_from_row(row) for row in rows), count


def invitation_names() -> dict[int, str]:
    with connection() as conn:
        return {row["id"]: row["name"] for row in conn.execute("SELECT id,name FROM invitations")}


def edit_invitation(
    *,
    actor_id: int,
    invitation_id: int,
    name: str | None = None,
    note: str | None = None,
    expires_at: str | None = None,
    change_expiry: bool = False,
    max_uses: int | None = None,
    enabled: bool | None = None,
) -> Invitation:
    with connection(write=True) as conn:
        actor = require_admin(conn, actor_id)
        before = require_invitation(conn, invitation_id)
        maximum = before.max_uses if max_uses is None else max_uses
        if maximum < 0 or (maximum and maximum < before.used_count):
            raise AuthOperationError("次数上限不能小于已使用次数", 422)
        conn.execute(
            "UPDATE invitations SET name=?,note=?,expires_at=?,max_uses=?,enabled=? WHERE id=?",
            (
                before.name if name is None else name,
                before.note if note is None else note,
                expires_at if change_expiry else before.expires_at,
                maximum,
                before.enabled if enabled is None else enabled,
                invitation_id,
            ),
        )
        after = require_invitation(conn, invitation_id)
        record_audit(
            conn,
            actor=actor.username,
            action="invitation.update",
            target=str(invitation_id),
            before=asdict(before),
            after=asdict(after),
        )
        return after


def list_uses(invitation_id: int, *, page: int = 1, page_size: int = 20) -> tuple[tuple[InvitationUse, ...], int]:
    with connection() as conn:
        require_invitation(conn, invitation_id)
        count = conn.execute("SELECT COUNT(*) FROM invitation_uses WHERE invitation_id=?", (invitation_id,)).fetchone()[
            0
        ]
        rows = conn.execute(
            """SELECT u.id AS user_id,u.username,u.display_name,r.registered_at
               FROM invitation_uses r JOIN users u ON r.user_id=u.id WHERE r.invitation_id=?
               ORDER BY r.registered_at DESC LIMIT ? OFFSET ?""",
            (invitation_id, page_size, (page - 1) * page_size),
        ).fetchall()
    return tuple(InvitationUse(**dict(row)) for row in rows), count


def register_user(*, username: str, password_hash: str, invite_code: str) -> User:
    """Create account and consume invitation under one serialized transaction."""
    with connection(write=True) as conn:
        row = conn.execute("SELECT * FROM registration_policy WHERE id=1").fetchone()
        policy = RegistrationPolicy(RegistrationMode(row["mode"]), row["max_users"])
        if not registration_open(policy):
            raise AuthOperationError("当前暂未开放注册，请联系管理员。", 503)
        invitation = None
        if policy.mode == RegistrationMode.INVITE:
            row = conn.execute("SELECT * FROM invitations WHERE code_digest=?", (code_digest(invite_code),)).fetchone()
            invitation = invitation_from_row(row) if row else None
            if invitation is None or invitation_status(invitation) != "active":
                raise AuthOperationError("需要有效的邀请码才能注册。", 403)
        if policy.max_users and conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] >= policy.max_users:
            raise AuthOperationError("注册人数已达到上限，请联系管理员。")
        user = insert_user(
            conn,
            username=username,
            password_hash=password_hash,
            student_id=username,
            display_name=username,
            source="invite" if invitation else "open",
            invitation_id=invitation.id if invitation else None,
        )
        if invitation:
            conn.execute("UPDATE invitations SET used_count=used_count+1 WHERE id=?", (invitation.id,))
            conn.execute(
                "INSERT INTO invitation_uses(user_id,invitation_id,registered_at) VALUES(?,?,?)",
                (user.id, invitation.id, now_iso()),
            )
        return user


def import_legacy_policy(*, mode: RegistrationMode, code: str, expires_at: str | None, max_users: int) -> None:
    """One-shot explicit migration; never overwrite an already managed policy."""
    if max_users < 0:
        raise AuthOperationError("注册容量无效", 422)
    if expires_at:
        expires_at = parse_time(expires_at).astimezone(timezone.utc).isoformat()
    with connection(write=True) as conn:
        current = conn.execute("SELECT * FROM registration_policy WHERE id=1").fetchone()
        if current["legacy_imported"] or conn.execute("SELECT COUNT(*) FROM invitations").fetchone()[0]:
            raise AuthOperationError("注册策略已经初始化，不能再次导入旧配置")
        if mode == RegistrationMode.INVITE and code:
            insert_invitation(
                conn, code=code, name="迁移的原邀请码", note="历史注册来源未知", expires_at=expires_at, max_uses=0
            )
        conn.execute(
            "UPDATE registration_policy SET mode=?,max_users=?,legacy_imported=1 WHERE id=1", (mode.value, max_users)
        )
        record_audit(
            conn,
            actor="local-cli",
            action="registration.import_legacy",
            target="registration",
            after={"mode": mode.value, "max_users": max_users},
        )
