"""
Backend state persistence for sessions and chat history.

This module keeps the in-memory session list and chat history in sync with
`var/chat_history/backend_state.json`, and it can also restore legacy per-session
history files that predate the consolidated state file.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import ds_course_agent.shared.config as config
from ds_course_agent.api.timestamps import parse_timestamp
from ds_course_agent.api.title_generation import (
    DEFAULT_SESSION_TITLE,
    build_fallback_session_title,
    should_repair_stored_title,
)

STATE_FILE = Path(config.CHAT_HISTORY_DIR) / "backend_state.json"
logger = logging.getLogger(__name__)

_sessions: dict[str, dict] = {}
_chat_history: dict[str, list[dict]] = {}
_deleted_session_ids: set[str] = set()
_state_lock = threading.RLock()
_save_lock = threading.Lock()
_last_save_time: float = 0.0
_primary_identity: tuple[int, int, int, int] | None = None
_primary_path: Path | None = None

_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class StatePersistenceError(RuntimeError):
    """History cannot be safely recovered or replaced; the original is preserved."""


@dataclass(frozen=True)
class _PersistedState:
    sessions: dict[str, dict[str, Any]]
    history: dict[str, list[dict[str, Any]]]
    deleted_ids: set[str]


def _decode_state(data: bytes) -> _PersistedState:
    payload = json.loads(data)
    if not isinstance(payload, dict):
        raise ValueError("state must be an object")
    sessions = payload.get("sessions")
    history = payload.get("chat_history")
    deleted = payload.get("deleted_session_ids", [])
    if not isinstance(sessions, dict) or not all(isinstance(value, dict) for value in sessions.values()):
        raise ValueError("invalid sessions")
    if not isinstance(history, dict) or not all(
        isinstance(messages, list) and all(isinstance(item, dict) for item in messages) for messages in history.values()
    ):
        raise ValueError("invalid chat history")
    if not isinstance(deleted, list) or not all(isinstance(item, str) for item in deleted):
        raise ValueError("invalid deleted session ids")
    return _PersistedState(sessions, history, set(deleted))


def _atomic_write(path: Path, data: bytes) -> None:
    """Publish a complete, flushed file; a failed write leaves the old file intact."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if hasattr(os, "O_DIRECTORY"):
            directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _file_identity(path: Path) -> tuple[int, int, int, int] | None:
    """Return a cheap replacement detector without parsing the full snapshot."""

    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)


def _quarantine(path: Path, *, label: str) -> Path | None:
    """Move an unreadable snapshot aside so startup can continue without deletion."""

    if not path.exists():
        return None
    archive = path.with_name(f"{path.name}.{label}.{uuid4().hex}")
    try:
        os.replace(path, archive)
    except OSError:
        logger.exception("Unable to quarantine corrupt history file: %s", path)
        return None
    return archive


def _read_persisted_state() -> _PersistedState:
    global _primary_identity, _primary_path
    _primary_path = STATE_FILE
    backup = STATE_FILE.with_suffix(".json.bak")
    original = STATE_FILE.read_bytes() if STATE_FILE.exists() else None
    if original is not None:
        try:
            return _decode_state(original)
        except (ValueError, UnicodeError):
            logger.error("Chat history is invalid; attempting recovery from its last valid snapshot")
    elif not backup.exists():
        _quarantine(STATE_FILE, label="corrupt")
        _primary_identity = None
        logger.critical(
            "Chat history primary snapshot was unreadable and no backup exists; corrupt file was quarantined and service starts with empty history"
        )
        return _PersistedState({}, {}, set())
    try:
        backup_data = backup.read_bytes()
        restored = _decode_state(backup_data)
    except (OSError, ValueError, UnicodeError) as exc:
        _quarantine(STATE_FILE, label="corrupt")
        _quarantine(backup, label="corrupt")
        _primary_identity = None
        logger.critical(
            "Chat history snapshots were unreadable; corrupt files were quarantined and service starts with empty history: %s",
            exc,
        )
        return _PersistedState({}, {}, set())
    if original is not None:
        if _quarantine(STATE_FILE, label="corrupt") is None and STATE_FILE.exists():
            raise StatePersistenceError("Chat history recovery could not quarantine the corrupt primary snapshot")
    _atomic_write(STATE_FILE, backup_data)
    _primary_identity = _file_identity(STATE_FILE)
    logger.warning(
        "Chat history recovered from its last valid snapshot; newer changes may need recovery from the archive"
    )
    return restored


@contextmanager
def state_lock() -> Iterator[None]:
    """Serialize all in-memory state mutations across routers."""

    with _state_lock:
        yield


def _coerce_legacy_message(raw: dict, fallback_ts: datetime) -> dict | None:
    if not isinstance(raw, dict):
        return None

    if "role" in raw and "content" in raw:
        return {
            "role": raw.get("role", "assistant"),
            "content": raw.get("content", ""),
            "timestamp": raw.get("timestamp") or fallback_ts.isoformat(),
            "sources": raw.get("sources"),
            "family": raw.get("family"),
            "intent": raw.get("intent"),
            "execution_mode": raw.get("execution_mode"),
            "retrieval_attempted": bool(raw.get("retrieval_attempted", False)),
            "used_retrieval": bool(raw.get("used_retrieval", False)),
            "degraded": bool(raw.get("degraded", False)),
            "progress": raw.get("progress"),
            "progress_events": raw.get("progress_events") or raw.get("progressEvents"),
            "metadata": raw.get("metadata"),
        }

    message_type = raw.get("type")
    data = raw.get("data", {})
    if not isinstance(data, dict):
        data = {}

    if message_type in {"human", "ai"}:
        return {
            "role": "user" if message_type == "human" else "assistant",
            "content": data.get("content", ""),
            "timestamp": data.get("timestamp") or fallback_ts.isoformat(),
            "sources": None,
        }

    return None


def _legacy_session_path(session_id: str) -> Path:
    return STATE_FILE.parent / session_id


def _delete_legacy_session_file(session_id: str) -> bool:
    legacy_path = _legacy_session_path(session_id)
    if not legacy_path.exists() or not legacy_path.is_file():
        return False

    try:
        legacy_path.unlink()
        return True
    except Exception:
        return False


def _load_legacy_chat_file(path: Path) -> list[dict] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    if not isinstance(payload, list):
        return None

    fallback_ts = datetime.fromtimestamp(path.stat().st_mtime)
    messages = []
    for item in payload:
        message = _coerce_legacy_message(item, fallback_ts)
        if message:
            messages.append(message)

    return messages or None


def _derive_session_metadata(session_id: str, messages: list[dict], fallback_ts: datetime) -> dict:
    user_messages = [
        message.get("content", "").strip()
        for message in messages
        if message.get("role") == "user" and message.get("content")
    ]
    title = build_fallback_session_title(user_messages[0]) if user_messages else DEFAULT_SESSION_TITLE
    created_at = parse_timestamp(messages[0].get("timestamp"), fallback_ts) if messages else fallback_ts
    updated_at = parse_timestamp(messages[-1].get("timestamp"), fallback_ts) if messages else fallback_ts

    return {
        "title": title,
        "title_source": "legacy",
        "student_id": "legacy_import",
        "created_at": created_at.isoformat(),
        "updated_at": updated_at.isoformat(),
        "message_count": len(messages),
        "legacy_session_id": session_id,
    }


def _restore_sessions_from_legacy_files() -> bool:
    changed = False
    if not STATE_FILE.parent.exists():
        return False

    for path in STATE_FILE.parent.iterdir():
        if not path.is_file():
            continue
        if path.name == STATE_FILE.name or path.suffix:
            continue
        if not _UUID_PATTERN.match(path.name):
            continue
        if path.name in _deleted_session_ids:
            continue

        messages = _load_legacy_chat_file(path)
        if not messages:
            continue

        if path.name not in _chat_history:
            _chat_history[path.name] = messages
            changed = True

        if path.name not in _sessions:
            fallback_ts = datetime.fromtimestamp(path.stat().st_mtime)
            _sessions[path.name] = _derive_session_metadata(path.name, _chat_history[path.name], fallback_ts)
            changed = True

    return changed


def _repair_session_metadata() -> bool:
    changed = False
    for session_id, messages in list(_chat_history.items()):
        if session_id in _deleted_session_ids:
            if session_id in _chat_history:
                del _chat_history[session_id]
                changed = True
            if session_id in _sessions:
                del _sessions[session_id]
                changed = True
            continue

        if session_id not in _sessions:
            fallback_ts = datetime.now()
            _sessions[session_id] = _derive_session_metadata(session_id, messages, fallback_ts)
            changed = True
            continue

        session = _sessions[session_id]

        user_messages = [
            message.get("content", "").strip()
            for message in messages
            if message.get("role") == "user" and message.get("content")
        ]
        if not user_messages:
            continue

        current_title = str(session.get("title") or "")
        title_source = session.get("title_source")
        if should_repair_stored_title(user_messages[0], current_title, title_source):
            repaired_title = build_fallback_session_title(user_messages[0])
            if repaired_title and repaired_title != current_title:
                session["title"] = repaired_title
                session["title_source"] = "repaired"
                session["title_repaired_from"] = current_title
                changed = True

    return changed


def purge_session(session_id: str) -> bool:
    with state_lock():
        changed = False

        if session_id in _sessions:
            del _sessions[session_id]
            changed = True

        if session_id in _chat_history:
            del _chat_history[session_id]
            changed = True

        if session_id not in _deleted_session_ids:
            _deleted_session_ids.add(session_id)
            changed = True

        if _delete_legacy_session_file(session_id):
            changed = True

        if changed:
            _save()

        return changed


def _load() -> None:
    global _primary_identity, _primary_path
    _primary_path = STATE_FILE
    restored = _read_persisted_state()
    changed = False
    # Consumers hold references to these containers; reloading must not orphan them.
    _sessions.clear()
    _sessions.update(restored.sessions)
    _chat_history.clear()
    _chat_history.update(restored.history)
    _deleted_session_ids.clear()
    _deleted_session_ids.update(restored.deleted_ids)

    # 清理 _deleted_session_ids 中不存在的 session（只做内存清理，不修改文件）
    for session_id in list(_deleted_session_ids):
        if session_id in _sessions:
            del _sessions[session_id]
            changed = True
        if session_id in _chat_history:
            del _chat_history[session_id]
            changed = True

    # 只在内存中清理，不在文件中也删除（避免大量 deleted_session_ids 积累）
    # 注意：_deleted_session_ids 的主要作用是防止恢复旧文件，不要清理它

    changed = _restore_sessions_from_legacy_files() or changed
    changed = _repair_session_metadata() or changed
    if changed:
        _save()
    else:
        _primary_identity = _file_identity(STATE_FILE)


def _save() -> None:
    global _primary_identity, _primary_path
    with _state_lock:
        with _save_lock:
            data = json.dumps(
                {
                    "sessions": _sessions,
                    "chat_history": _chat_history,
                    "deleted_session_ids": sorted(_deleted_session_ids),
                },
                ensure_ascii=False,
                default=lambda obj: obj.isoformat() if hasattr(obj, "isoformat") else str(obj),
            ).encode("utf-8")
            current_identity = _file_identity(STATE_FILE)
            if _primary_path != STATE_FILE:
                _primary_path = STATE_FILE
                _primary_identity = current_identity
            if _primary_identity != current_identity:
                raise StatePersistenceError(
                    "Refusing to overwrite history changed outside this process; reload or recover the snapshot"
                )

            temporary: Path | None = None
            backup_temporary: Path | None = None
            backup = STATE_FILE.with_suffix(".json.bak")
            try:
                STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(
                    dir=STATE_FILE.parent,
                    prefix=f".{STATE_FILE.name}.",
                    suffix=".tmp",
                    delete=False,
                ) as handle:
                    temporary = Path(handle.name)
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())

                # Preserve the previous valid inode without rereading or copying
                # the complete JSON. Hard links make the backup update metadata-only.
                if STATE_FILE.exists():
                    try:
                        backup_temporary = backup.with_name(f".{backup.name}.{uuid4().hex}.tmp")
                        os.link(STATE_FILE, backup_temporary)
                        os.replace(backup_temporary, backup)
                        backup_temporary = None
                    except OSError:
                        logger.warning("Unable to refresh history backup with a hard link; retaining the prior backup")
                os.replace(temporary, STATE_FILE)
                directory_fd = os.open(STATE_FILE.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
                _primary_identity = _file_identity(STATE_FILE)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
                if backup_temporary is not None:
                    backup_temporary.unlink(missing_ok=True)


_load()
