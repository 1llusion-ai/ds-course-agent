"""Content-free, session-owned facts for administrative usage aggregation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import ds_course_agent.shared.config as config
from ds_course_agent.shared.database import connect_sqlite


@dataclass(frozen=True)
class ChatFact:
    student_id: str
    course_id: str
    session_id: str
    turn_id: str
    role: str
    created_at: str
    generation_status: str


@dataclass(frozen=True)
class SessionFact:
    student_id: str
    course_id: str
    session_id: str
    created_at: str


@dataclass(frozen=True)
class ChatFacts:
    messages: tuple[ChatFact, ...]
    sessions: tuple[SessionFact, ...]


def read_chat_facts(*, start: str, end: str, course_id: str | None = None, student_id: str | None = None) -> ChatFacts:
    """Read persisted facts in UTC interval; never load message bodies or trigger backfill."""
    path = Path(config.APP_DB_PATH)
    if not path.exists():
        return ChatFacts((), ())
    conn = connect_sqlite(path)
    try:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='messages'").fetchone() is None:
            return ChatFacts((), ())
        where = ["julianday(created_at)>=julianday(?)", "julianday(created_at)<julianday(?)"]
        values: list[object] = [start, end]
        for column, value in (("course_id", course_id), ("student_id", student_id)):
            if value is not None:
                where.append(f"{column}=?")
                values.append(value)
        clause = " AND ".join(where)
        messages = conn.execute(
            f"""SELECT student_id,course_id,session_id,COALESCE(turn_id,id) AS turn_id,role,created_at,generation_status
                FROM messages WHERE {clause} AND role IN ('user','assistant') ORDER BY created_at,id""",
            values,
        ).fetchall()
        sessions = conn.execute(
            f"SELECT student_id,course_id,id AS session_id,created_at FROM sessions WHERE {clause}",
            values,
        ).fetchall()
        return ChatFacts(
            tuple(ChatFact(**dict(row)) for row in messages), tuple(SessionFact(**dict(row)) for row in sessions)
        )
    finally:
        conn.close()
