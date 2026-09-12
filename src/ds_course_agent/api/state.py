"""
Backend state persistence for sessions and chat history.

This module keeps the in-memory session list and chat history in sync with
`var/chat_history/backend_state.json`, and it can also restore legacy per-session
history files that predate the consolidated state file.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import ds_course_agent.shared.config as config
from ds_course_agent.api.timestamps import parse_timestamp
from ds_course_agent.api.title_generation import (
    DEFAULT_SESSION_TITLE,
    build_fallback_session_title,
    should_repair_stored_title,
)

STATE_FILE = Path(config.CHAT_HISTORY_DIR) / "backend_state.json"

_sessions: dict[str, dict] = {}
_chat_history: dict[str, list[dict]] = {}
_deleted_session_ids: set[str] = set()
_state_lock = threading.RLock()
_save_lock = threading.Lock()
_last_save_time: float = 0.0

_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


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


def _load():
    global _sessions, _chat_history, _deleted_session_ids
    changed = False

    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            _sessions = data.get("sessions", {})
            _chat_history = data.get("chat_history", {})
            _deleted_session_ids = set(data.get("deleted_session_ids", []))
        except Exception:
            _sessions = {}
            _chat_history = {}
            _deleted_session_ids = set()
    else:
        _sessions = {}
        _chat_history = {}
        _deleted_session_ids = set()

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


def _save():
    with _state_lock:
        with _save_lock:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            STATE_FILE.write_text(
                json.dumps(
                    {
                        "sessions": _sessions,
                        "chat_history": _chat_history,
                        "deleted_session_ids": sorted(_deleted_session_ids),
                    },
                    ensure_ascii=False,
                    default=lambda obj: obj.isoformat() if hasattr(obj, "isoformat") else str(obj),
                ),
                encoding="utf-8",
            )


_load()
