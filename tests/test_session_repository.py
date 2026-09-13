from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ds_course_agent.api.session_repository import (
    MessageRecord,
    SessionRecord,
    SQLiteSessionRepository,
)

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
