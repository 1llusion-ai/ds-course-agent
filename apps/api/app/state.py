"""
Backend state persistence for sessions and chat history.

This module keeps the in-memory session list and chat history in sync with
`chat_history/backend_state.json`, and it can also restore legacy per-session
history files that predate the consolidated state file.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJECT_ROOT))

import utils.config as config

DEFAULT_SESSION_TITLE = "新会话"
STATE_FILE = Path(config.CHAT_HISTORY_DIR) / "backend_state.json"

_sessions: Dict[str, dict] = {}
_chat_history: Dict[str, List[dict]] = {}
_deleted_session_ids: set[str] = set()

_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _parse_timestamp(value, fallback: datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except Exception:
            return fallback
    return fallback


def _coerce_legacy_message(raw: dict, fallback_ts: datetime) -> dict | None:
    if not isinstance(raw, dict):
        return None

    if "role" in raw and "content" in raw:
        return {
            "role": raw.get("role", "assistant"),
            "content": raw.get("content", ""),
            "timestamp": raw.get("timestamp") or fallback_ts.isoformat(),
            "sources": raw.get("sources"),
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


def _load_legacy_chat_file(path: Path) -> List[dict] | None:
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


def _derive_session_metadata(session_id: str, messages: List[dict], fallback_ts: datetime) -> dict:
    user_messages = [
        message.get("content", "").strip()
        for message in messages
        if message.get("role") == "user" and message.get("content")
    ]
    title = (user_messages[0][:20] if user_messages else "") or DEFAULT_SESSION_TITLE
    created_at = _parse_timestamp(messages[0].get("timestamp"), fallback_ts) if messages else fallback_ts
    updated_at = _parse_timestamp(messages[-1].get("timestamp"), fallback_ts) if messages else fallback_ts

    return {
        "title": title,
        "student_id": "default_student",
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

        if session_id in _sessions:
            continue

        fallback_ts = datetime.now()
        _sessions[session_id] = _derive_session_metadata(session_id, messages, fallback_ts)
        changed = True

    return changed


def purge_session(session_id: str) -> bool:
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

    for session_id in list(_deleted_session_ids):
        if session_id in _sessions:
            del _sessions[session_id]
            changed = True
        if session_id in _chat_history:
            del _chat_history[session_id]
            changed = True

    changed = _restore_sessions_from_legacy_files() or changed
    changed = _repair_session_metadata() or changed
    if changed:
        _save()


def _save():
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
