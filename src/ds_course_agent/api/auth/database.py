"""Versioned local identity storage; registration policy has one database owner."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import ds_course_agent.shared.config as config
from ds_course_agent.shared.database import Migration, SQLiteMigrationRunner, connect_sqlite

AUTH_MIGRATIONS = (
    Migration(
        1,
        "existing_local_users",
        (
            """CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL, student_id TEXT NOT NULL, display_name TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
            "CREATE INDEX IF NOT EXISTS idx_users_student_id ON users(student_id)",
        ),
    ),
    Migration(
        2,
        "account_permissions_and_registration",
        (
            "CREATE UNIQUE INDEX idx_users_identity ON users(student_id)",
            "ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'student' CHECK(role IN ('student','observer','admin'))",
            "ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','disabled'))",
            "ALTER TABLE users ADD COLUMN session_version INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE users ADD COLUMN last_login_at TEXT",
            "ALTER TABLE users ADD COLUMN registration_source TEXT NOT NULL DEFAULT 'legacy'",
            """CREATE TABLE invitations (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
            code_digest TEXT NOT NULL UNIQUE, code_hint TEXT NOT NULL, expires_at TEXT,
            max_uses INTEGER NOT NULL CHECK(max_uses>=0), used_count INTEGER NOT NULL DEFAULT 0 CHECK(used_count>=0),
            enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)), created_at TEXT NOT NULL)""",
            "ALTER TABLE users ADD COLUMN invitation_id INTEGER REFERENCES invitations(id)",
            """CREATE TABLE registration_policy (
            id INTEGER PRIMARY KEY CHECK(id=1), mode TEXT NOT NULL CHECK(mode IN ('closed','invite','open')),
            max_users INTEGER NOT NULL CHECK(max_users>=0), legacy_imported INTEGER NOT NULL DEFAULT 0)""",
            "INSERT INTO registration_policy(id,mode,max_users) VALUES(1,'closed',0)",
            """CREATE TABLE invitation_uses (
            user_id INTEGER PRIMARY KEY REFERENCES users(id), invitation_id INTEGER NOT NULL REFERENCES invitations(id),
            registered_at TEXT NOT NULL)""",
            "CREATE INDEX idx_invitation_uses_code ON invitation_uses(invitation_id,registered_at)",
            """CREATE TABLE admin_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT, actor TEXT NOT NULL, action TEXT NOT NULL,
            target TEXT NOT NULL, created_at TEXT NOT NULL, before_json TEXT NOT NULL, after_json TEXT NOT NULL)""",
            "CREATE INDEX idx_admin_audit_created ON admin_audit(created_at)",
        ),
    ),
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db() -> None:
    """Migrate identity schema without applying legacy environment registration settings."""
    SQLiteMigrationRunner(Path(config.AUTH_DB_PATH)).apply(AUTH_MIGRATIONS)


@contextmanager
def connection(*, write: bool = False) -> Iterator[sqlite3.Connection]:
    """Serialize write checks and mutations; always release the SQLite connection."""
    init_db()
    conn = connect_sqlite(config.AUTH_DB_PATH)
    try:
        if write:
            conn.execute("BEGIN IMMEDIATE")
        yield conn
        if write:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
