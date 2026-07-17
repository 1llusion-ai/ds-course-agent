"""SQLite-backed local user store for API authentication."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import ds_course_agent.shared.config as config


def _db_path() -> Path:
    return Path(config.AUTH_DB_PATH)


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the auth database schema if needed."""

    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                student_id TEXT NOT NULL,
                display_name TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_student_id ON users(student_id)")
        conn.commit()


def _row_to_user(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def get_user_by_username(username: str) -> dict[str, Any] | None:
    """Return a user dict by username, or ``None`` when not found."""

    init_db()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, username, password_hash, student_id, display_name, created_at, updated_at
            FROM users
            WHERE username = ?
            """,
            (username,),
        ).fetchone()
    return _row_to_user(row)


def create_or_update_user(
    *,
    username: str,
    password_hash: str,
    student_id: str,
    display_name: str,
) -> dict[str, Any]:
    """Create or update a local user account."""

    init_db()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO users (username, password_hash, student_id, display_name)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
                password_hash = excluded.password_hash,
                student_id = excluded.student_id,
                display_name = excluded.display_name,
                updated_at = CURRENT_TIMESTAMP
            """,
            (username, password_hash, student_id, display_name),
        )
        conn.commit()
    user = get_user_by_username(username)
    if user is None:  # pragma: no cover - sqlite failure would be exceptional
        raise RuntimeError(f"Failed to create user {username!r}")
    return user
