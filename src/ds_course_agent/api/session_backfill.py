"""One-time legacy session/message backfill into the application database."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ds_course_agent.api.chat_sessions import message_from_dict, message_to_dict
from ds_course_agent.api.session_repository import MessageRecord, SessionRecord, SQLiteSessionRepository
from ds_course_agent.api.timestamps import parse_timestamp
from ds_course_agent.api.title_generation import DEFAULT_SESSION_TITLE, build_fallback_session_title

_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SessionBackfillPlan:
    sessions: tuple[SessionRecord, ...]
    messages: tuple[MessageRecord, ...]
    deleted_session_ids: tuple[str, ...]
    invalid_files: int = 0

    def summary(self) -> dict[str, int]:
        return {
            "sessions_discovered": len(self.sessions),
            "messages_discovered": len(self.messages),
            "deleted_session_ids": len(self.deleted_session_ids),
            "invalid_files": self.invalid_files,
        }


def build_session_backfill_plan(history_dir: str | Path) -> SessionBackfillPlan:
    root = Path(history_dir)
    state_file = root / "backend_state.json"
    sessions: dict[str, dict[str, Any]] = {}
    histories: dict[str, list[dict[str, Any]]] = {}
    deleted_ids: set[str] = set()
    invalid_files = 0
    source_fallback = (
        datetime.fromtimestamp(state_file.stat().st_mtime, timezone.utc)
        if state_file.exists()
        else datetime(1970, 1, 1, tzinfo=timezone.utc)
    )

    if state_file.exists():
        try:
            payload = json.loads(state_file.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("backend state must be an object")
            sessions.update(payload.get("sessions") or {})
            histories.update(payload.get("chat_history") or {})
            deleted_ids.update(str(item) for item in payload.get("deleted_session_ids") or [])
        except Exception:
            invalid_files += 1

    if root.exists():
        for path in root.iterdir():
            if not path.is_file() or not _UUID_PATTERN.fullmatch(path.name):
                continue
            if path.name in deleted_ids or path.name in histories:
                continue
            messages = _read_legacy_messages(path)
            if messages is None:
                invalid_files += 1
                continue
            histories[path.name] = messages

    session_records: list[SessionRecord] = []
    message_records: list[MessageRecord] = []
    for session_id in sorted(set(sessions) | set(histories)):
        if session_id in deleted_ids:
            continue
        raw_messages = histories.get(session_id) or []
        raw_session = sessions.get(session_id) if isinstance(sessions.get(session_id), dict) else {}
        fallback = source_fallback
        created_at = parse_timestamp(
            raw_session.get("created_at") or (raw_messages[0].get("timestamp") if raw_messages else None),
            fallback,
        )
        updated_at = parse_timestamp(
            raw_session.get("updated_at") or (raw_messages[-1].get("timestamp") if raw_messages else None),
            created_at,
        )
        first_question = next(
            (str(item.get("content") or "") for item in raw_messages if item.get("role") == "user"),
            "",
        )
        title = str(raw_session.get("title") or "").strip()
        if not title:
            title = build_fallback_session_title(first_question) if first_question else DEFAULT_SESSION_TITLE
        student_id = str(raw_session.get("student_id") or "legacy_import")
        session_records.append(
            SessionRecord(
                session_id=session_id,
                student_id=student_id,
                title=title,
                title_source=str(raw_session.get("title_source") or "legacy"),
                created_at=created_at,
                updated_at=updated_at,
                title_generation_attempts=int(raw_session.get("title_generation_attempts") or 0),
                title_generation_pending=bool(raw_session.get("title_generation_pending", False)),
                title_repaired_from=raw_session.get("title_repaired_from"),
                legacy_session_id=raw_session.get("legacy_session_id") or session_id,
            )
        )
        for position, raw_message in enumerate(raw_messages):
            normalized = message_to_dict(message_from_dict(raw_message))
            normalized["timestamp"] = parse_timestamp(
                raw_message.get("timestamp"),
                created_at + timedelta(microseconds=position),
            ).isoformat()
            normalized["turn_id"] = raw_message.get("turn_id")
            normalized["langchain_payload"] = raw_message.get("langchain_payload")
            message_records.append(
                _message_record(
                    session_id=session_id,
                    student_id=student_id,
                    position=position,
                    data=normalized,
                )
            )

    return SessionBackfillPlan(
        sessions=tuple(session_records),
        messages=tuple(message_records),
        deleted_session_ids=tuple(sorted(deleted_ids)),
        invalid_files=invalid_files,
    )


def apply_session_backfill(
    plan: SessionBackfillPlan,
    *,
    database: str | Path,
) -> dict[str, int]:
    return SQLiteSessionRepository(database).import_snapshot(
        plan.sessions,
        plan.messages,
        plan.deleted_session_ids,
    )


def _read_legacy_messages(path: Path) -> list[dict[str, Any]] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, list):
        return None
    fallback = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    messages = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        if "role" in item and "content" in item:
            normalized = dict(item)
            normalized.setdefault("timestamp", fallback.isoformat())
            messages.append(normalized)
            continue
        message_type = item.get("type")
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        if message_type in {"human", "ai", "system", "tool"}:
            messages.append(
                {
                    "role": {"human": "user", "ai": "assistant"}.get(message_type, message_type),
                    "content": data.get("content", ""),
                    "timestamp": data.get("timestamp") or fallback.isoformat(),
                    "langchain_payload": item,
                }
            )
    return messages


def _message_record(
    *,
    session_id: str,
    student_id: str,
    position: int,
    data: dict[str, Any],
) -> MessageRecord:
    identity_payload = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(f"{session_id}\0{position}\0{identity_payload}".encode()).hexdigest()[:24]
    return MessageRecord(
        message_id=f"legacy_message_{digest}",
        session_id=session_id,
        student_id=student_id,
        position=position,
        turn_id=data.get("turn_id"),
        role=str(data.get("role") or "assistant"),
        content=str(data.get("content") or ""),
        created_at=parse_timestamp(data.get("timestamp"), datetime.now(timezone.utc)),
        route_family=data.get("family"),
        route_intent=data.get("intent"),
        execution_mode=data.get("execution_mode"),
        generation_status=str(data.get("generation_status") or "completed"),
        generation_error=data.get("generation_error"),
        retrieval_attempted=bool(data.get("retrieval_attempted", False)),
        used_retrieval=bool(data.get("used_retrieval", False)),
        degraded=bool(data.get("degraded", False)),
        web_search_requested=bool(data.get("web_search_requested", False)),
        web_search_used=bool(data.get("web_search_used", False)),
        web_search_status=str(data.get("web_search_status") or "not_requested"),
        web_search_reason=data.get("web_search_reason"),
        sources=data.get("sources"),
        progress=data.get("progress"),
        progress_events=data.get("progress_events"),
        metadata=data.get("metadata"),
        langchain_payload=data.get("langchain_payload"),
    )


__all__ = [
    "SessionBackfillPlan",
    "apply_session_backfill",
    "build_session_backfill_plan",
]
