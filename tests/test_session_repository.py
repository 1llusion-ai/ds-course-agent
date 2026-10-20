from __future__ import annotations

import ast
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ds_course_agent.api.session_repository import (
    DEFAULT_COURSE_ID,
    SESSION_MIGRATIONS,
    MessageRecord,
    SessionRecord,
    SQLiteSessionRepository,
)
from ds_course_agent.shared.database import SQLiteMigrationRunner

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _session(student_id: str = "student-1", session_id: str = "session-1") -> SessionRecord:
    now = datetime.now(timezone.utc)
    return SessionRecord(
        session_id=session_id,
        student_id=student_id,
        title="测试会话",
        title_source="manual",
        created_at=now,
        updated_at=now,
    )


def _message(message_id: str, role: str, content: str, *, position: int = -1) -> MessageRecord:
    return MessageRecord(
        message_id=message_id,
        session_id="session-1",
        student_id="student-1",
        position=position,
        role=role,
        content=content,
        created_at=datetime.now(timezone.utc),
    )


def test_session_repository_preserves_order_and_student_isolation(tmp_path) -> None:
    repository = SQLiteSessionRepository(tmp_path / "app.db")
    repository.create_session(_session())
    repository.create_session(_session("student-2", "session-2"))

    stored = repository.append_messages(
        (
            _message("message-1", "user", "问题"),
            _message("message-2", "assistant", "回答"),
        )
    )

    assert [record.position for record in stored] == [0, 1]
    assert [record.content for record in repository.list_messages("student-1", "session-1")] == ["问题", "回答"]
    assert repository.get_session("student-2", "session-1") is None
    assert repository.list_sessions("student-2")[0].session_id == "session-2"


def test_session_delete_removes_messages_and_keeps_tombstone(tmp_path) -> None:
    path = tmp_path / "app.db"
    repository = SQLiteSessionRepository(path)
    repository.create_session(_session())
    repository.append_message(_message("message-1", "user", "问题"))

    assert repository.delete_session("student-1", "session-1") is True
    assert repository.find_session("session-1") is None
    assert repository.list_messages_by_session("session-1") == ()
    assert repository.import_snapshot((_session(),), (), ("session-1",))["sessions_skipped"] == 1


def test_deleted_session_rejects_new_messages(tmp_path) -> None:
    repository = SQLiteSessionRepository(tmp_path / "app.db")
    repository.create_session(_session())
    assert repository.delete_session("student-1", "session-1") is True

    with pytest.raises(KeyError, match="session-1"):
        repository.append_message(_message("message-1", "user", "问题"))

    assert repository.list_messages_by_session("session-1") == ()


def test_import_snapshot_is_idempotent_and_rolls_back_conflicts(tmp_path) -> None:
    repository = SQLiteSessionRepository(tmp_path / "app.db")
    session = _session()
    message = _message("legacy-1", "user", "问题", position=0)

    first = repository.import_snapshot((session,), (message,))
    second = repository.import_snapshot((session,), (message,))

    assert first["sessions_imported"] == 1
    assert first["messages_imported"] == 1
    assert second["sessions_skipped"] == 1
    assert second["messages_skipped"] == 1

    conflicting = MessageRecord(**{**message.__dict__, "message_id": "legacy-2", "content": "冲突"})
    with pytest.raises(ValueError, match="message import conflict"):
        repository.import_snapshot((_session("student-3", "session-3"), session), (conflicting,))
    assert repository.find_session("session-3") is None


def test_deleting_first_message_resequences_remaining_positions(tmp_path) -> None:
    repository = SQLiteSessionRepository(tmp_path / "app.db")
    repository.create_session(_session())
    stored = repository.append_messages(
        (
            _message("message-1", "user", "一"),
            _message("message-2", "assistant", "二"),
            _message("message-3", "user", "三"),
        )
    )

    assert repository.delete_message("student-1", "session-1", stored[0].message_id) is True
    remaining = repository.list_messages("student-1", "session-1")
    assert [record.position for record in remaining] == [0, 1]
    assert [record.content for record in remaining] == ["二", "三"]


def test_old_session_schema_migrates_to_default_course_and_is_idempotent(tmp_path) -> None:
    path = tmp_path / "legacy.db"
    SQLiteMigrationRunner(path).apply(SESSION_MIGRATIONS[:1])
    timestamp = "2026-01-01T00:00:00+00:00"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("legacy-session", "student-1", "旧会话", "manual", timestamp, timestamp, None, 0, 0, None, None),
        )
        connection.execute(
            "INSERT INTO messages (id, session_id, student_id, position, role, content, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("legacy-message", "legacy-session", "student-1", 0, "user", "旧消息", timestamp),
        )

    repository = SQLiteSessionRepository(path)
    assert repository.get_session("student-1", "legacy-session").course_id == DEFAULT_COURSE_ID
    assert repository.list_messages("student-1", "legacy-session")[0].course_id == DEFAULT_COURSE_ID
    assert repository.migrate() == ()

    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1
        assert connection.execute("SELECT course_id FROM sessions").fetchone()[0] == DEFAULT_COURSE_ID


def test_same_student_session_isolated_by_course_scope(tmp_path) -> None:
    path = tmp_path / "scoped.db"
    repository = SQLiteSessionRepository(path)
    now = datetime.now(timezone.utc)
    default_session = _session()
    other_session = SessionRecord(
        session_id=default_session.session_id,
        student_id=default_session.student_id,
        title="另一门课程",
        title_source="manual",
        created_at=now,
        updated_at=now,
        course_id="digital-literacy",
    )
    repository.create_session(default_session)
    repository.create_session(other_session)
    repository.append_message(_message("default-message", "user", "默认课程", position=0))
    repository.append_message(
        MessageRecord(
            message_id="other-message",
            session_id=other_session.session_id,
            student_id=other_session.student_id,
            role="user",
            content="另一课程",
            created_at=now,
            position=0,
            course_id=other_session.course_id,
        )
    )

    assert repository.list_sessions("student-1", DEFAULT_COURSE_ID)[0].title == "测试会话"
    assert repository.list_sessions("student-1", "digital-literacy")[0].title == "另一门课程"
    assert repository.get_session("student-1", "session-1", "digital-literacy").title == "另一门课程"
    assert repository.get_session("student-1", "session-1", "missing-course") is None
    assert [item.content for item in repository.list_messages("student-1", "session-1")] == ["默认课程"]


def test_course_session_identity_has_exactly_one_student_owner(tmp_path) -> None:
    repository = SQLiteSessionRepository(tmp_path / "owner.db")
    repository.create_session(_session("student-1", "same-session"))
    with pytest.raises(sqlite3.IntegrityError):
        repository.create_session(_session("student-2", "same-session"))
    assert repository.get_session("student-2", "same-session") is None
    assert repository.find_session("same-session").student_id == "student-1"


def test_api_session_persistence_stays_behind_repository_boundary() -> None:
    assert not (REPOSITORY_ROOT / "src/ds_course_agent/api/state.py").exists()
    assert not (REPOSITORY_ROOT / "src/ds_course_agent/shared/session_repository.py").exists()

    api_paths = (
        REPOSITORY_ROOT / "src/ds_course_agent/api/chat_sessions.py",
        REPOSITORY_ROOT / "src/ds_course_agent/api/routers/sessions.py",
    )
    for path in api_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports_sqlite = any(
            (isinstance(node, ast.Import) and any(alias.name == "sqlite3" for alias in node.names))
            or (isinstance(node, ast.ImportFrom) and node.module == "sqlite3")
            for node in ast.walk(tree)
        )
        called_attributes = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert not imports_sqlite
        assert {"execute", "executemany", "executescript"}.isdisjoint(called_attributes)
