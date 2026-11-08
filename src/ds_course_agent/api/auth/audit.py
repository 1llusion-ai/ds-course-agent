"""Transactional management audit records containing explicitly selected public fields."""

from __future__ import annotations

import json
import sqlite3

from .contracts import AuditEntry
from .database import connection, now_iso


def record_audit(
    conn: sqlite3.Connection,
    *,
    actor: str,
    action: str,
    target: str,
    before: dict[str, object] | None = None,
    after: dict[str, object] | None = None,
) -> None:
    conn.execute(
        "INSERT INTO admin_audit(actor,action,target,created_at,before_json,after_json) VALUES(?,?,?,?,?,?)",
        (
            actor,
            action,
            target,
            now_iso(),
            json.dumps(before or {}, ensure_ascii=False),
            json.dumps(after or {}, ensure_ascii=False),
        ),
    )


def list_audit(*, q: str = "", page: int = 1, page_size: int = 20) -> tuple[tuple[AuditEntry, ...], int]:
    where = "WHERE instr(actor,?)>0 OR instr(action,?)>0 OR instr(target,?)>0"
    with connection() as conn:
        count = conn.execute(f"SELECT COUNT(*) FROM admin_audit {where}", (q, q, q)).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM admin_audit {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            (q, q, q, page_size, (page - 1) * page_size),
        ).fetchall()
    return tuple(
        AuditEntry(
            id=row["id"],
            actor=row["actor"],
            action=row["action"],
            target=row["target"],
            created_at=row["created_at"],
            before=json.loads(row["before_json"]),
            after=json.loads(row["after_json"]),
        )
        for row in rows
    ), int(count)
