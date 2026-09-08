"""Chat-session persistence, locking, ownership, and title tasks."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool

from ds_course_agent.api.schemas.chat import ChatMessage
from ds_course_agent.api.state import DEFAULT_SESSION_TITLE, _chat_history, _sessions, state_lock
from ds_course_agent.api.state import _save as _save_state
from ds_course_agent.api.timestamps import parse_timestamp, timestamps_match
from ds_course_agent.api.title_generation import (
    SESSION_TITLE_MAX_CHARS,
    _clean_generated_title,
    _finalize_title,
    build_fallback_session_title,
    looks_like_unprocessed_question_title,
)

logger = logging.getLogger(__name__)
_SESSION_LOCK_POLL_SECONDS = 0.01
_title_generation_pending: set[str] = set()
_title_generation_tasks: set[asyncio.Task] = set()
_history_locks: dict[str, threading.RLock] = {}
_history_locks_guard = threading.Lock()
_session_operation_locks: dict[str, threading.Lock] = {}
_session_operation_locks_guard = threading.Lock()


def reset_title_generation_state() -> None:
    """Clear in-flight title bookkeeping for isolated application tests."""

    _title_generation_pending.clear()


def has_web_source(sources: list[dict[str, Any]] | None) -> bool:
    """Return whether source metadata contains an external web reference."""

    for source in sources or []:
        if not isinstance(source, dict):
            continue
        if source.get("source") == "web" or source.get("url") or source.get("href") or source.get("link"):
            return True
    return False


def _extract_response_text(response: Any) -> str:
    if hasattr(response, "content"):
        return str(response.content or "").strip()
    if isinstance(response, str):
        return response.strip()
    return str(response).strip()


async def _generate_session_title_with_source(question: str) -> tuple[str, str]:
    """Generate a session title.

    Returns ``(title, source)`` where source is ``llm`` or ``heuristic``.
    The heuristic fallback is deliberately topic-like, not a raw question slice.
    """

    prompt = f"""请把下面这个问题概括成一个会话标题，必须满足以下要求：
1. 不超过 {SESSION_TITLE_MAX_CHARS} 个字符（汉字、英文字母、数字均算 1 个字符）
2. 必须保留核心语义
3. 生成短语式标题，不要直接截取原问题
4. 直接返回标题，不要任何解释或引号

问题：{question}

标题："""

    try:
        from ds_course_agent.shared.llm import get_chat_model

        llm = get_chat_model()
        response = await run_in_threadpool(llm.invoke, prompt)
        raw_title = _extract_response_text(response)
        cleaned_title = _clean_generated_title(raw_title)
        title = _finalize_title(question, cleaned_title)
        source = (
            "heuristic"
            if not cleaned_title or looks_like_unprocessed_question_title(question, cleaned_title)
            else "llm"
        )
        return title, source
    except Exception:
        logger.warning("会话标题 LLM 生成失败，已使用规则标题降级。", exc_info=True)
        return build_fallback_session_title(question), "heuristic"


async def generate_session_title(question: str) -> str:
    """用 LLM 将问题概括为标题；失败时返回规则标题。"""

    title, _source = await _generate_session_title_with_source(question)
    return title


def message_to_dict(msg: ChatMessage) -> dict[str, Any]:
    """Serialize one API chat message for backend state persistence."""

    return {
        "role": msg.role,
        "content": msg.content,
        "timestamp": msg.timestamp.isoformat() if msg.timestamp else datetime.now().isoformat(),
        "sources": msg.sources or None,
        "family": msg.family.value if msg.family else None,
        "intent": msg.intent.value if msg.intent else None,
        "execution_mode": msg.execution_mode.value if msg.execution_mode else None,
        "retrieval_attempted": msg.retrieval_attempted,
        "used_retrieval": msg.used_retrieval,
        "degraded": msg.degraded,
        "progress": msg.progress or None,
        "progress_events": msg.progress_events or None,
        "web_search_requested": msg.web_search_requested,
        "web_search_used": msg.web_search_used,
        "web_search_status": msg.web_search_status,
        "web_search_reason": msg.web_search_reason,
        "generation_status": msg.generation_status,
        "generation_error": msg.generation_error,
        "metadata": msg.metadata or None,
    }


def message_from_dict(data: dict[str, Any]) -> ChatMessage:
    """Restore one API chat message from backend state."""

    ts = parse_timestamp(data.get("timestamp"), datetime.now())
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    web_search_requested = bool(data.get("web_search_requested", metadata.get("web_search", False)))
    web_search_used = bool(data.get("web_search_used", has_web_source(data.get("sources"))))
    return ChatMessage(
        role=data.get("role", "assistant"),
        content=data.get("content", ""),
        timestamp=ts or datetime.now(),
        sources=data.get("sources"),
        family=data.get("family"),
        intent=data.get("intent"),
        execution_mode=data.get("execution_mode"),
        retrieval_attempted=bool(data.get("retrieval_attempted", False)),
        used_retrieval=bool(data.get("used_retrieval", False)),
        degraded=bool(data.get("degraded", False)),
        progress=data.get("progress"),
        progress_events=data.get("progress_events") or data.get("progressEvents"),
        web_search_requested=web_search_requested,
        web_search_used=web_search_used,
        web_search_status=data.get(
            "web_search_status",
            "used"
            if web_search_requested and web_search_used
            else ("not_used" if web_search_requested else "not_requested"),
        ),
        web_search_reason=data.get("web_search_reason"),
        generation_status=data.get("generation_status", "completed"),
        generation_error=data.get("generation_error"),
        metadata=data.get("metadata"),
    )


def _ensure_session_history(session_id: str) -> None:
    if session_id not in _chat_history:
        _chat_history[session_id] = []


def _history_lock(session_id: str) -> threading.RLock:
    with _history_locks_guard:
        lock = _history_locks.get(session_id)
        if lock is None:
            lock = threading.RLock()
            _history_locks[session_id] = lock
        return lock


def session_operation_lock(session_id: str) -> threading.Lock:
    """Return the lock that serializes complete turns for one session."""

    with _session_operation_locks_guard:
        lock = _session_operation_locks.get(session_id)
        if lock is None:
            lock = threading.Lock()
            _session_operation_locks[session_id] = lock
        return lock


async def acquire_threading_lock(lock: threading.Lock) -> None:
    """Acquire a regular threading lock without occupying asyncio's executor."""

    while True:
        if lock.acquire(blocking=False):
            return
        await asyncio.sleep(_SESSION_LOCK_POLL_SECONDS)


@asynccontextmanager
async def session_operation_guard(session_id: str) -> AsyncIterator[None]:
    """Serialize complete send operations for one session.

    Without this, two concurrent sends can interleave user/assistant messages
    and call the agent with mismatched per-session context.  The blocking lock
    acquisition is polled asynchronously so other sessions remain concurrent
    without tying request lifetime to asyncio's default executor.
    """

    lock = session_operation_lock(session_id)
    await acquire_threading_lock(lock)
    try:
        yield
    finally:
        lock.release()


def append_message_locked(session_id: str, message: ChatMessage, *, save: bool = True) -> dict[str, Any]:
    """Append one message under the per-session history lock."""

    with _history_lock(session_id):
        with state_lock():
            item = message_to_dict(message)
            _ensure_session_history(session_id)
            _chat_history[session_id].append(item)
            if save:
                _save_state()
            return item


def remove_message_by_identity(session_id: str, message_item: dict[str, Any], *, save: bool = True) -> bool:
    """Remove exactly the message object previously appended for this turn."""

    with _history_lock(session_id):
        with state_lock():
            history = _chat_history.get(session_id)
            if not history:
                return False
            for index in range(len(history) - 1, -1, -1):
                if history[index] is message_item:
                    del history[index]
                    if save:
                        _save_state()
                    return True
            return False


def replace_message_by_identity(
    session_id: str,
    message_item: dict[str, Any],
    message: ChatMessage,
    *,
    save: bool = True,
) -> bool:
    """Replace exactly one stored message while preserving turn order."""

    with _history_lock(session_id):
        with state_lock():
            history = _chat_history.get(session_id)
            if not history:
                return False
            for index, item in enumerate(history):
                if item is message_item:
                    history[index] = message_to_dict(message)
                    if save:
                        _save_state()
                    return True
            return False


def find_stopped_assistant_turn(session_id: str, message_timestamp: datetime) -> dict[str, Any]:
    """Return the latest stopped assistant item for continuation."""

    with _history_lock(session_id):
        with state_lock():
            history = _chat_history.get(session_id, [])
            if not history:
                raise HTTPException(status_code=409, detail="没有可继续生成的回答")

            target_index = len(history) - 1
            target = history[target_index]
            if (
                target.get("role") != "assistant"
                or target.get("generation_status") != "stopped"
                or not timestamps_match(target.get("timestamp"), message_timestamp)
            ):
                raise HTTPException(status_code=409, detail="只能继续当前会话最后一条已停止的回答")
            return target


def update_session_metadata(session_id: str, timestamp: str | None = None, *, save: bool = True) -> None:
    """Refresh message count and update time for an existing session."""

    with state_lock():
        if session_id not in _sessions:
            return

        _sessions[session_id]["message_count"] = len(_chat_history.get(session_id, []))
        _sessions[session_id]["updated_at"] = timestamp or datetime.now().isoformat()
        if save:
            _save_state()


def _first_user_message(session_id: str, fallback: str = "") -> str:
    for item in _chat_history.get(session_id, []):
        if item.get("role") == "user" and item.get("content"):
            return str(item.get("content") or "")
    return fallback


def _should_schedule_title_generation(session_id: str, message: str, *, is_first_message: bool) -> bool:
    if session_id in _title_generation_pending:
        return False

    session = _sessions.get(session_id)
    if not session:
        return False

    title = str(session.get("title") or "").strip()
    source = session.get("title_source")
    attempts = int(session.get("title_generation_attempts") or 0)

    if source == "manual":
        return False
    if source == "llm":
        return False

    # Always name a brand-new default session once. If the LLM is temporarily
    # unavailable, retry on a couple of later sends while keeping the heuristic
    # title visible in the meantime.
    if not title or title == DEFAULT_SESSION_TITLE:
        return True
    if source in {"default", "heuristic", "fallback", "llm_failed", "legacy", "repaired"}:
        return attempts < 3
    if is_first_message and looks_like_unprocessed_question_title(message, title):
        return True
    return False


def _apply_immediate_fallback_title(session_id: str, message: str, *, is_first_message: bool) -> None:
    """Give a new/default session a usable title before async LLM naming finishes.

    Title generation intentionally runs in the background so fast replies (for
    example scope-guard refusals) do not wait for the LLM.  Without an immediate
    heuristic title, the frontend can refresh sessions before the background job
    completes and still see ``新会话``.  That makes newly-created chats look
    unnamed and can confuse "新建聊天" navigation.  The background job may still
    replace this title with an LLM-polished one later.
    """

    session = _sessions.get(session_id)
    if not session:
        return
    if session.get("title_source") == "manual":
        return

    title = str(session.get("title") or "").strip()
    should_apply = (
        not title
        or title == DEFAULT_SESSION_TITLE
        or (is_first_message and looks_like_unprocessed_question_title(message, title))
    )
    if not should_apply:
        return

    fallback = build_fallback_session_title(message)
    if not fallback or fallback == title:
        return

    with state_lock():
        session["title"] = fallback
        session["title_source"] = "heuristic"
        session["title_generation_pending"] = True
        _save_state()


def schedule_title_generation(session_id: str, message: str, *, is_first_message: bool) -> None:
    """Generate or retry the session title in the background without blocking replies."""
    if not _should_schedule_title_generation(session_id, message, is_first_message=is_first_message):
        return

    _apply_immediate_fallback_title(session_id, message, is_first_message=is_first_message)
    _title_generation_pending.add(session_id)

    async def _bg_generate_title():
        try:
            seed_message = _first_user_message(session_id, message)
            # Keep compatibility with tests/extensions that monkeypatch the
            # older single-value helper while the default implementation still
            # delegates to the richer source-aware generator.
            generated_title = await generate_session_title(seed_message)
            source = (
                "heuristic"
                if (
                    generated_title == build_fallback_session_title(seed_message)
                    or looks_like_unprocessed_question_title(seed_message, generated_title)
                )
                else "llm"
            )
            with state_lock():
                if session_id in _sessions:
                    _sessions[session_id]["title"] = generated_title
                    _sessions[session_id]["title_source"] = source
                    _sessions[session_id].pop("title_generation_pending", None)
                    _sessions[session_id]["title_generation_attempts"] = (
                        int(_sessions[session_id].get("title_generation_attempts") or 0) + 1
                    )
                    _save_state()
        except Exception:
            logger.debug("会话标题生成失败", exc_info=True)
            with state_lock():
                if session_id in _sessions:
                    _sessions[session_id]["title"] = build_fallback_session_title(message)
                    _sessions[session_id]["title_source"] = "heuristic"
                    _sessions[session_id].pop("title_generation_pending", None)
                    _sessions[session_id]["title_generation_attempts"] = (
                        int(_sessions[session_id].get("title_generation_attempts") or 0) + 1
                    )
                    _save_state()
        finally:
            _title_generation_pending.discard(session_id)

    task = asyncio.create_task(_bg_generate_title())
    _title_generation_tasks.add(task)
    add_done_callback = getattr(task, "add_done_callback", None)
    if callable(add_done_callback):
        add_done_callback(_title_generation_tasks.discard)
    else:  # Compatibility with tests/extensions that monkeypatch create_task.
        _title_generation_tasks.discard(task)


def save_state() -> None:
    """Persist the current backend session and message state."""

    _save_state()


def message_count(session_id: str) -> int:
    """Return the number of persisted messages for a session."""

    return len(_chat_history.get(session_id, []))


def list_messages(session_id: str) -> list[dict[str, Any]]:
    """Return a stable list snapshot of persisted message dictionaries."""

    with _history_lock(session_id):
        return list(_chat_history.get(session_id, []))


def clear_messages(session_id: str) -> None:
    """Delete all persisted messages for one session."""

    with _history_lock(session_id):
        with state_lock():
            _chat_history.pop(session_id, None)
            update_session_metadata(session_id, save=False)
            _save_state()


def ensure_session_owner(session_id: str, student_id: str) -> None:
    """Raise an HTTP error unless the student owns the session."""

    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="会话不存在")
    if _sessions[session_id].get("student_id") != student_id:
        raise HTTPException(status_code=403, detail="无权访问此会话")


__all__ = [
    "acquire_threading_lock",
    "append_message_locked",
    "clear_messages",
    "ensure_session_owner",
    "find_stopped_assistant_turn",
    "generate_session_title",
    "has_web_source",
    "message_from_dict",
    "message_count",
    "message_to_dict",
    "list_messages",
    "remove_message_by_identity",
    "replace_message_by_identity",
    "reset_title_generation_state",
    "save_state",
    "schedule_title_generation",
    "session_operation_guard",
    "session_operation_lock",
    "update_session_metadata",
]
