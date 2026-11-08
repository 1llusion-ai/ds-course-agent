"""Typed local account repository and atomic account administration."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import ds_course_agent.shared.config as config

from .audit import record_audit
from .contracts import AccountStatus, AuthOperationError, Role, User
from .database import connection, init_db, now_iso

__all__ = ["config", "init_db"]


def user_from_row(row: sqlite3.Row) -> User:
    values = dict(row)
    for key in ("created_at", "updated_at", "last_login_at"):
        if values[key] is not None:
            instant = datetime.fromisoformat(values[key].replace("Z", "+00:00"))
            if instant.tzinfo is None:
                instant = instant.replace(tzinfo=timezone.utc)
            values[key] = instant.astimezone(timezone.utc).isoformat()
    return User(**{**values, "role": Role(row["role"]), "status": AccountStatus(row["status"])})


def get_user_by_username(username: str) -> User | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    return user_from_row(row) if row else None


def get_user_by_student_id(student_id: str) -> User | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE student_id=?", (student_id,)).fetchone()
    return user_from_row(row) if row else None


def get_user(user_id: int) -> User:
    with connection() as conn:
        return require_user(conn, user_id)


def require_user(conn: sqlite3.Connection, user_id: int) -> User:
    row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if row is None:
        raise AuthOperationError("账号不存在", 404)
    return user_from_row(row)


def require_admin(conn: sqlite3.Connection, actor_id: int) -> User:
    """Recheck authorization inside the write transaction."""
    actor = require_user(conn, actor_id)
    if actor.role != Role.ADMIN or actor.status != AccountStatus.ACTIVE:
        raise AuthOperationError("需要管理员权限", 403)
    return actor


def insert_user(
    conn: sqlite3.Connection,
    *,
    username: str,
    password_hash: str,
    student_id: str,
    display_name: str,
    role: Role = Role.STUDENT,
    source: str = "manual",
    invitation_id: int | None = None,
) -> User:
    """Insert in the caller's transaction; collision never replaces an account."""
    try:
        cursor = conn.execute(
            """INSERT INTO users(username,password_hash,student_id,display_name,role,registration_source,
               invitation_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                username,
                password_hash,
                student_id,
                display_name,
                role.value,
                source,
                invitation_id,
                now_iso(),
                now_iso(),
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise AuthOperationError("该用户名或学习身份已存在") from exc
    return require_user(conn, int(cursor.lastrowid))


def create_or_update_user(*, username: str, password_hash: str, student_id: str, display_name: str) -> User:
    """Local provisioning; the learning identity of an existing account is immutable."""
    with connection(write=True) as conn:
        row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if row is None:
            user = insert_user(
                conn, username=username, password_hash=password_hash, student_id=student_id, display_name=display_name
            )
        else:
            user = user_from_row(row)
            if user.student_id != student_id:
                raise AuthOperationError("不能更改已有账号的学习身份")
            conn.execute(
                "UPDATE users SET password_hash=?,display_name=?,updated_at=?,session_version=session_version+1 WHERE id=?",
                (password_hash, display_name, now_iso(), user.id),
            )
            user = require_user(conn, user.id)
        record_audit(
            conn, actor="local-cli", action="account.provision", target=user.username, after={"role": user.role.value}
        )
        return user


def update_user_password(*, username: str, password_hash: str, expected_hash: str | None = None) -> User | None:
    """Replace password and revoke sessions, with compare-and-set for self service."""
    with connection(write=True) as conn:
        row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if row is None:
            return None
        if expected_hash is not None and row["password_hash"] != expected_hash:
            raise AuthOperationError("密码已发生变化，请重新登录", 401)
        conn.execute(
            "UPDATE users SET password_hash=?,updated_at=?,session_version=session_version+1 WHERE username=?",
            (password_hash, now_iso(), username),
        )
        record_audit(
            conn,
            actor=username if expected_hash is not None else "local-cli",
            action="account.password_reset",
            target=username,
        )
        return require_user(conn, row["id"])


def record_login(user: User) -> User:
    """Avoid issuing a session if the account changed during password verification."""
    with connection(write=True) as conn:
        current = require_user(conn, user.id)
        if current.status != AccountStatus.ACTIVE or current.session_version != user.session_version:
            raise AuthOperationError("账号状态已发生变化，请重新登录", 401)
        conn.execute("UPDATE users SET last_login_at=? WHERE id=?", (now_iso(), user.id))
        return require_user(conn, user.id)


def list_users(
    *,
    q: str = "",
    role: Role | None = None,
    status: AccountStatus | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[tuple[User, ...], int]:
    conditions = ["(instr(username,?)>0 OR instr(display_name,?)>0 OR instr(student_id,?)>0)"]
    values: list[object] = [q, q, q]
    for column, value in (("role", role), ("status", status)):
        if value is not None:
            conditions.append(f"{column}=?")
            values.append(value.value)
    if created_from:
        conditions.append("julianday(created_at)>=julianday(?)")
        values.append(created_from)
    if created_to:
        conditions.append("julianday(created_at)<julianday(?)")
        values.append(created_to)
    where = " AND ".join(conditions)
    with connection() as conn:
        count = conn.execute(f"SELECT COUNT(*) FROM users WHERE {where}", values).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM users WHERE {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            (*values, page_size, (page - 1) * page_size),
        ).fetchall()
    return tuple(user_from_row(row) for row in rows), count


def all_users() -> tuple[User, ...]:
    """Local aggregate analysis identities; credentials never enter response projections."""
    with connection() as conn:
        return tuple(user_from_row(row) for row in conn.execute("SELECT * FROM users"))


def create_managed_user(*, actor_id: int, username: str, password_hash: str, display_name: str, role: Role) -> User:
    with connection(write=True) as conn:
        actor = require_admin(conn, actor_id)
        user = insert_user(
            conn,
            username=username,
            password_hash=password_hash,
            student_id=username,
            display_name=display_name,
            role=role,
        )
        record_audit(
            conn,
            actor=actor.username,
            action="account.create",
            target=user.username,
            after={"role": role.value, "display_name": display_name},
        )
        return user


def edit_user(
    *,
    actor_id: int,
    user_id: int,
    display_name: str | None = None,
    role: Role | None = None,
    status: AccountStatus | None = None,
) -> User:
    with connection(write=True) as conn:
        actor = require_admin(conn, actor_id)
        user = require_user(conn, user_id)
        new_role, new_status = role or user.role, status or user.status
        if user.role == Role.ADMIN and user.status == AccountStatus.ACTIVE:
            if new_role != Role.ADMIN or new_status != AccountStatus.ACTIVE:
                count = conn.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND status='active'").fetchone()[0]
                if count <= 1:
                    raise AuthOperationError("不能停用或降级最后一名有效管理员")
        name = display_name if display_name is not None else user.display_name
        revoke = int(new_status != user.status or new_role != user.role)
        conn.execute(
            "UPDATE users SET display_name=?,role=?,status=?,session_version=session_version+?,updated_at=? WHERE id=?",
            (name, new_role.value, new_status.value, revoke, now_iso(), user_id),
        )
        record_audit(
            conn,
            actor=actor.username,
            action="account.update",
            target=user.username,
            before={"display_name": user.display_name, "role": user.role.value, "status": user.status.value},
            after={"display_name": name, "role": new_role.value, "status": new_status.value},
        )
        return require_user(conn, user_id)


def revoke_sessions(*, actor_id: int, user_id: int, password_hash: str | None = None) -> None:
    with connection(write=True) as conn:
        actor = require_admin(conn, actor_id)
        user = require_user(conn, user_id)
        conn.execute("UPDATE users SET session_version=session_version+1,updated_at=? WHERE id=?", (now_iso(), user_id))
        if password_hash is not None:
            conn.execute("UPDATE users SET password_hash=? WHERE id=?", (password_hash, user_id))
        record_audit(
            conn,
            actor=actor.username,
            action="account.password_reset" if password_hash else "account.revoke_sessions",
            target=user.username,
        )


def bootstrap_admin(username: str) -> User:
    """Explicit local recovery/bootstrap command, with an audit entry."""
    with connection(write=True) as conn:
        row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if row is None:
            raise AuthOperationError("账号不存在，请先创建账号", 404)
        user = user_from_row(row)
        conn.execute(
            "UPDATE users SET role='admin',status='active',session_version=session_version+1,updated_at=? WHERE id=?",
            (now_iso(), user.id),
        )
        record_audit(
            conn,
            actor="local-cli",
            action="account.bootstrap_admin",
            target=username,
            before={"role": user.role.value, "status": user.status.value},
            after={"role": "admin", "status": "active"},
        )
        return require_user(conn, user.id)
