"""Invitation lifecycle and atomic registration quota enforcement."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

import ds_course_agent.shared.config as config

from .audit import record_audit
from .contracts import (
    INVITATION_CODE_MAX_LENGTH,
    AuthOperationError,
    Invitation,
    InvitationUse,
    RegistrationMode,
    User,
)
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


def invitation_audit_snapshot(invitation: Invitation) -> dict[str, object]:
    return {key: value for key, value in asdict(invitation).items() if key != "code"}


def invitation_status(invitation: Invitation) -> str:
    if not invitation.enabled:
        return "disabled"
    if invitation.expires_at and parse_time(invitation.expires_at) <= datetime.now(timezone.utc):
        return "expired"
    return "active"


def get_registration_mode() -> RegistrationMode:
    with connection() as conn:
        return registration_mode(conn)


def registration_mode(conn: sqlite3.Connection) -> RegistrationMode:
    return RegistrationMode(conn.execute("SELECT mode FROM registration_policy WHERE id=1").fetchone()["mode"])


def registration_open(mode: RegistrationMode) -> bool:
    return mode == RegistrationMode.INVITE or (
        mode == RegistrationMode.OPEN and config.APP_ENV in {"development", "test"}
    )


def update_registration_mode(*, actor_id: int, mode: RegistrationMode) -> RegistrationMode:
    if mode not in {RegistrationMode.CLOSED, RegistrationMode.INVITE}:
        raise AuthOperationError("注册模式无效", 422)
    with connection(write=True) as conn:
        actor = require_admin(conn, actor_id)
        previous = registration_mode(conn)
        conn.execute("UPDATE registration_policy SET mode=?,legacy_imported=1 WHERE id=1", (mode.value,))
        record_audit(
            conn,
            actor=actor.username,
            action="registration.update",
            target="registration",
            before={"mode": previous.value},
            after={"mode": mode.value},
        )
    return mode


def create_invitation(
    *, actor_id: int, name: str, note: str, expires_at: str | None, code: str = ""
) -> tuple[Invitation, str]:
    code = code.strip() or secrets.token_urlsafe(24)
    if len(code) > INVITATION_CODE_MAX_LENGTH or not code.isprintable():
        raise AuthOperationError(f"注册码须为单行可见字符，最多 {INVITATION_CODE_MAX_LENGTH} 个字符", 422)
    with connection(write=True) as conn:
        actor = require_admin(conn, actor_id)
        invitation = insert_invitation(conn, code=code, name=name, note=note, expires_at=expires_at)
        record_audit(
            conn,
            actor=actor.username,
            action="invitation.create",
            target=str(invitation.id),
            after=invitation_audit_snapshot(invitation),
        )
    return invitation, code


def insert_invitation(
    conn: sqlite3.Connection, *, code: str, name: str, note: str, expires_at: str | None
) -> Invitation:
    cursor = conn.execute(
        """INSERT INTO invitations(name,note,code_digest,code,expires_at,created_at)
           VALUES(?,?,?,?,?,?) ON CONFLICT(code_digest) DO NOTHING""",
        (
            name,
            note,
            code_digest(code),
            code,
            expires_at,
            now_iso(),
        ),
    )
    if cursor.rowcount == 0:
        raise AuthOperationError("该注册码已存在")
    return require_invitation(conn, int(cursor.lastrowid))


def require_invitation(conn: sqlite3.Connection, invitation_id: int) -> Invitation:
    row = conn.execute("SELECT * FROM invitations WHERE id=? AND deleted_at IS NULL", (invitation_id,)).fetchone()
    if row is None:
        raise AuthOperationError("注册码不存在", 404)
    return invitation_from_row(row)


def list_invitations(*, page: int = 1, page_size: int = 20) -> tuple[tuple[Invitation, ...], int]:
    with connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM invitations WHERE deleted_at IS NULL").fetchone()[0]
        rows = conn.execute(
            "SELECT * FROM invitations WHERE deleted_at IS NULL ORDER BY id DESC LIMIT ? OFFSET ?",
            (page_size, (page - 1) * page_size),
        ).fetchall()
    return tuple(invitation_from_row(row) for row in rows), count


def invitation_names() -> dict[int, str]:
    with connection() as conn:
        return {row["id"]: row["name"] for row in conn.execute("SELECT id,name FROM invitations")}


def invitation_summary(*, expires_within_days: int = 7) -> dict[str, int]:
    """Status counts for current invitations in the administrative overview."""
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=expires_within_days)
    with connection() as conn:
        rows = conn.execute("SELECT * FROM invitations WHERE deleted_at IS NULL").fetchall()
    invitations = [invitation_from_row(row) for row in rows]
    return {
        "total": len(invitations),
        "expiring": sum(
            item.enabled and item.expires_at is not None and now < parse_time(item.expires_at) <= horizon
            for item in invitations
        ),
    }


def edit_invitation(
    *,
    actor_id: int,
    invitation_id: int,
    name: str | None = None,
    note: str | None = None,
    code: str | None = None,
    expires_at: str | None = None,
    change_expiry: bool = False,
    enabled: bool | None = None,
) -> Invitation:
    code = (code or "").strip()
    with connection(write=True) as conn:
        actor = require_admin(conn, actor_id)
        before = require_invitation(conn, invitation_id)
        if (
            code
            and not conn.execute(
                "SELECT 1 FROM invitations WHERE id=? AND code_digest=?", (invitation_id, code_digest(code))
            ).fetchone()
        ):
            raise AuthOperationError("输入的注册码与原码不一致", 422)
        conn.execute(
            "UPDATE invitations SET name=?,note=?,expires_at=?,enabled=?,code=COALESCE(?,code) WHERE id=?",
            (
                before.name if name is None else name,
                before.note if note is None else note,
                expires_at if change_expiry else before.expires_at,
                before.enabled if enabled is None else enabled,
                code or None,
                invitation_id,
            ),
        )
        after = require_invitation(conn, invitation_id)
        record_audit(
            conn,
            actor=actor.username,
            action="invitation.update",
            target=str(invitation_id),
            before=invitation_audit_snapshot(before),
            after=invitation_audit_snapshot(after),
        )
        return after


def delete_invitation(*, actor_id: int, invitation_id: int) -> None:
    """Remove the code from registration and management while retaining its usage history."""
    with connection(write=True) as conn:
        actor = require_admin(conn, actor_id)
        invitation = require_invitation(conn, invitation_id)
        conn.execute("UPDATE invitations SET enabled=0,code=NULL,deleted_at=? WHERE id=?", (now_iso(), invitation_id))
        record_audit(
            conn,
            actor=actor.username,
            action="invitation.delete",
            target=str(invitation_id),
            before=invitation_audit_snapshot(invitation),
        )


def list_uses(invitation_id: int, *, page: int = 1, page_size: int = 20) -> tuple[tuple[InvitationUse, ...], int]:
    with connection() as conn:
        require_invitation(conn, invitation_id)
        count = conn.execute("SELECT COUNT(*) FROM invitation_uses WHERE invitation_id=?", (invitation_id,)).fetchone()[
            0
        ]
        rows = conn.execute(
            """SELECT u.id AS user_id,u.username,u.display_name,r.registered_at,
                      d.user_id IS NOT NULL AS account_deleted
               FROM invitation_uses r JOIN users u ON r.user_id=u.id
               LEFT JOIN deleted_accounts d ON d.user_id=u.id WHERE r.invitation_id=?
               ORDER BY r.registered_at DESC LIMIT ? OFFSET ?""",
            (invitation_id, page_size, (page - 1) * page_size),
        ).fetchall()
    return tuple(InvitationUse(**{**dict(row), "account_deleted": bool(row["account_deleted"])}) for row in rows), count


def register_user(*, username: str, password_hash: str, invite_code: str) -> User:
    """Create an account and record invitation use in one serialized transaction."""
    with connection(write=True) as conn:
        mode = registration_mode(conn)
        if not registration_open(mode):
            raise AuthOperationError("当前暂未开放注册，请联系管理员。", 503)
        invitation = None
        if mode == RegistrationMode.INVITE:
            row = conn.execute(
                "SELECT * FROM invitations WHERE code_digest=? AND deleted_at IS NULL", (code_digest(invite_code),)
            ).fetchone()
            invitation = invitation_from_row(row) if row else None
            if invitation is None or invitation_status(invitation) != "active":
                raise AuthOperationError("需要有效的注册码才能注册。", 403)
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


def import_legacy_policy(*, mode: RegistrationMode, code: str, expires_at: str | None) -> None:
    """One-shot explicit migration; never overwrite an already managed policy."""
    if expires_at:
        expires_at = parse_time(expires_at).astimezone(timezone.utc).isoformat()
    with connection(write=True) as conn:
        current = conn.execute("SELECT * FROM registration_policy WHERE id=1").fetchone()
        if current["legacy_imported"] or conn.execute("SELECT COUNT(*) FROM invitations").fetchone()[0]:
            raise AuthOperationError("注册策略已经初始化，不能再次导入旧配置")
        if mode == RegistrationMode.INVITE and code:
            insert_invitation(conn, code=code, name="迁移的原注册码", note="历史注册来源未知", expires_at=expires_at)
        conn.execute("UPDATE registration_policy SET mode=?,legacy_imported=1 WHERE id=1", (mode.value,))
        record_audit(
            conn,
            actor="local-cli",
            action="registration.import_legacy",
            target="registration",
            after={"mode": mode.value},
        )
