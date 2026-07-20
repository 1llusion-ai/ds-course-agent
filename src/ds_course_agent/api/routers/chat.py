from dotenv import load_dotenv

from ..core_bridge import PROJECT_ROOT

env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    load_dotenv(env_path, override=True)

import asyncio
import json
import logging
import threading
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from ..auth.deps import get_current_student_id
from ..core_bridge import chat_with_history, stream_chat_with_history
from ..schemas.chat import ChatHistoryResponse, ChatMessage, ChatRequest, ChatResponse, ChatStreamRequest
from ..state import DEFAULT_SESSION_TITLE, _chat_history, _sessions, state_lock
from ..state import _save as _save_state
from ..title_generation import (
    SESSION_TITLE_MAX_CHARS,
    _clean_generated_title,
    _finalize_title,
    build_fallback_session_title,
    looks_like_unprocessed_question_title,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_STREAM_SENTINEL = object()
_STREAM_QUEUE_MAXSIZE = 128
_SESSION_LOCK_POLL_SECONDS = 0.01
_PROGRESS_DETAIL_STRING_LIMIT = 500
_PROGRESS_DETAIL_LIST_LIMIT = 5
_PROGRESS_DETAIL_DICT_LIMIT = 24
_PROGRESS_DETAIL_JSON_LIMIT = 6000
_STREAM_IDLE_TIMEOUT_SECONDS = 120.0


@dataclass(frozen=True)
class ActiveStreamJob:
    """In-process stream generation job visible to history/cancel endpoints."""

    student_id: str
    started_at: datetime
    cancel_event: threading.Event


_title_generation_pending: set[str] = set()
# Backward-compatible test/runtime hook. It now tracks only in-flight title jobs
# rather than "already generated" sessions.
_title_gen_cache = _title_generation_pending
_title_generation_tasks: set[asyncio.Task] = set()
_history_locks: dict[str, threading.RLock] = {}
_history_locks_guard = threading.Lock()
_session_operation_locks: dict[str, threading.Lock] = {}
_session_operation_locks_guard = threading.Lock()
_active_stream_jobs: dict[str, ActiveStreamJob] = {}
_active_stream_jobs_guard = threading.Lock()


def _extract_response_text(response) -> str:
    if hasattr(response, "content"):
        return str(response.content or "").strip()
    if isinstance(response, str):
        return response.strip()
    return str(response).strip()


def _compact_progress_detail_value(value, *, depth: int = 0):
    """Bound progress event details before persisting them to chat history."""

    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) <= _PROGRESS_DETAIL_STRING_LIMIT:
            return value
        return value[: _PROGRESS_DETAIL_STRING_LIMIT - 1].rstrip() + "…"
    if depth >= 3:
        return str(value)[:_PROGRESS_DETAIL_STRING_LIMIT]
    if isinstance(value, list):
        compacted = [
            _compact_progress_detail_value(item, depth=depth + 1) for item in value[:_PROGRESS_DETAIL_LIST_LIMIT]
        ]
        if len(value) > _PROGRESS_DETAIL_LIST_LIMIT:
            compacted.append({"_truncated_items": len(value) - _PROGRESS_DETAIL_LIST_LIMIT})
        return compacted
    if isinstance(value, dict):
        compacted: dict = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= _PROGRESS_DETAIL_DICT_LIMIT:
                compacted["_truncated_keys"] = len(value) - _PROGRESS_DETAIL_DICT_LIMIT
                break
            compacted[str(key)] = _compact_progress_detail_value(item, depth=depth + 1)
        return compacted
    return str(value)[:_PROGRESS_DETAIL_STRING_LIMIT]


def _compact_progress_details_for_history(details):
    if details is None:
        return None
    compacted = _compact_progress_detail_value(details)
    try:
        encoded = json.dumps(compacted, ensure_ascii=False)
    except TypeError:
        return str(compacted)[:_PROGRESS_DETAIL_JSON_LIMIT]
    if len(encoded) <= _PROGRESS_DETAIL_JSON_LIMIT:
        return compacted
    return {
        "truncated": True,
        "preview": encoded[: _PROGRESS_DETAIL_JSON_LIMIT - 1].rstrip() + "…",
    }


def _progress_phase_exists(progress_events: list[dict] | None, phase: str) -> bool:
    return any(str(event.get("phase") or "") == phase for event in progress_events or [] if isinstance(event, dict))


def _query_trace_has_stage(query_trace: dict | None, stage: str) -> bool:
    events = query_trace.get("events", []) if isinstance(query_trace, dict) else []
    return any(isinstance(event, dict) and event.get("stage") == stage for event in events)


def _query_trace_stage_has_status(query_trace: dict | None, stage: str, status: str) -> bool:
    events = query_trace.get("events", []) if isinstance(query_trace, dict) else []
    return any(
        isinstance(event, dict) and event.get("stage") == stage and event.get("status") == status for event in events
    )


def _has_web_source(sources: list[dict] | None) -> bool:
    for source in sources or []:
        if not isinstance(source, dict):
            continue
        if source.get("source") == "web" or source.get("url") or source.get("href") or source.get("link"):
            return True
    return False


def _web_search_turn_fields(
    *,
    requested: bool,
    used_retrieval: bool | None,
    progress_events: list[dict] | None = None,
    query_trace: dict | None = None,
    sources: list[dict] | None = None,
    error: str | None = None,
) -> dict:
    """Build explicit per-turn web-search state for the frontend."""

    if not requested:
        return {
            "web_search_requested": False,
            "web_search_used": False,
            "web_search_status": "not_requested",
            "web_search_reason": None,
        }

    used = bool(used_retrieval) or _has_web_source(sources)
    if used:
        return {
            "web_search_requested": True,
            "web_search_used": True,
            "web_search_status": "used",
            "web_search_reason": None,
        }

    if _progress_phase_exists(progress_events, "web_search_scope") or _query_trace_has_stage(
        query_trace,
        "web_search.scope_blocked",
    ):
        status = "blocked_by_scope"
        reason = "问题超出课程助教范围，本轮未进行通用联网搜索。"
    elif (
        _progress_phase_exists(progress_events, "web_search_error")
        or _query_trace_stage_has_status(query_trace, "web_search.no_results", "error")
        or error
        or _query_trace_stage_has_status(query_trace, "execute.web_search_tool", "error")
    ):
        status = "error"
        reason = str(error or "联网搜索暂时不可用。")
    elif _progress_phase_exists(progress_events, "web_search_results") and not _has_web_source(sources):
        status = "no_results"
        reason = "本轮联网搜索未获得可用结果。"
    elif _query_trace_has_stage(query_trace, "web_search.no_results"):
        status = "no_results"
        reason = "本轮联网搜索未获得可用结果。"
    else:
        status = "not_used"
        reason = "本轮未实际使用联网搜索。"

    return {
        "web_search_requested": True,
        "web_search_used": False,
        "web_search_status": status,
        "web_search_reason": reason,
    }


def _register_active_stream_job(session_id: str, student_id: str, cancel_event: threading.Event) -> datetime:
    started_at = datetime.now()
    with _active_stream_jobs_guard:
        _active_stream_jobs[session_id] = ActiveStreamJob(
            student_id=student_id,
            started_at=started_at,
            cancel_event=cancel_event,
        )
    return started_at


def _unregister_active_stream_job(session_id: str) -> None:
    with _active_stream_jobs_guard:
        _active_stream_jobs.pop(session_id, None)


def _active_stream_job_for(session_id: str, student_id: str) -> ActiveStreamJob | None:
    with _active_stream_jobs_guard:
        job = _active_stream_jobs.get(session_id)
        if not job or job.student_id != student_id:
            return None
        return job


def _active_stream_pending_fields(session_id: str, student_id: str) -> dict:
    job = _active_stream_job_for(session_id, student_id)
    if not job:
        return {"pending_generation": False, "pending_started_at": None}
    return {
        "pending_generation": True,
        "pending_started_at": job.started_at,
    }


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


async def _generate_session_title(question: str) -> str:
    """用 LLM 将问题概括为标题；失败时返回规则标题。"""

    title, _source = await _generate_session_title_with_source(question)
    return title


def _msg_to_dict(msg: ChatMessage) -> dict:
    return {
        "role": msg.role,
        "content": msg.content,
        "timestamp": msg.timestamp.isoformat() if msg.timestamp else datetime.now().isoformat(),
        "sources": msg.sources or None,
        "route": msg.route or None,
        "progress": msg.progress or None,
        "progress_events": msg.progress_events or None,
        "web_search_requested": msg.web_search_requested,
        "web_search_used": msg.web_search_used,
        "web_search_status": msg.web_search_status,
        "web_search_reason": msg.web_search_reason,
        "metadata": msg.metadata or None,
    }


def _msg_from_dict(data: dict) -> ChatMessage:
    ts = data.get("timestamp")
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts)
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    web_search_requested = bool(data.get("web_search_requested", metadata.get("web_search", False)))
    web_search_used = bool(data.get("web_search_used", _has_web_source(data.get("sources"))))
    return ChatMessage(
        role=data.get("role", "assistant"),
        content=data.get("content", ""),
        timestamp=ts or datetime.now(),
        sources=data.get("sources"),
        route=data.get("route"),
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


def _session_operation_lock(session_id: str) -> threading.Lock:
    with _session_operation_locks_guard:
        lock = _session_operation_locks.get(session_id)
        if lock is None:
            lock = threading.Lock()
            _session_operation_locks[session_id] = lock
        return lock


async def _acquire_threading_lock(lock: threading.Lock) -> None:
    """Acquire a regular threading lock without occupying asyncio's executor."""

    while True:
        if lock.acquire(blocking=False):
            return
        await asyncio.sleep(_SESSION_LOCK_POLL_SECONDS)


@asynccontextmanager
async def _session_operation_guard(session_id: str):
    """Serialize complete send operations for one session.

    Without this, two concurrent sends can interleave user/assistant messages
    and call the agent with mismatched per-session context.  The blocking lock
    acquisition is polled asynchronously so other sessions remain concurrent
    without tying request lifetime to asyncio's default executor.
    """

    lock = _session_operation_lock(session_id)
    await _acquire_threading_lock(lock)
    try:
        yield
    finally:
        lock.release()


def _append_message(session_id: str, message: ChatMessage, *, save: bool = True) -> None:
    with state_lock():
        _ensure_session_history(session_id)
        _chat_history[session_id].append(_msg_to_dict(message))
        if save:
            _save_state()


def _append_message_locked(session_id: str, message: ChatMessage, *, save: bool = True) -> dict:
    with _history_lock(session_id):
        with state_lock():
            item = _msg_to_dict(message)
            _ensure_session_history(session_id)
            _chat_history[session_id].append(item)
            if save:
                _save_state()
            return item


def _remove_message_by_identity(session_id: str, message_item: dict, *, save: bool = True) -> bool:
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


def _update_session_metadata(session_id: str, timestamp: str | None = None, *, save: bool = True) -> None:
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


def _schedule_title_generation(session_id: str, message: str, *, is_first_message: bool) -> None:
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
            generated_title = await _generate_session_title(seed_message)
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


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _ensure_session_owner(session_id: str, student_id: str) -> None:
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="会话不存在")
    if _sessions[session_id].get("student_id") != student_id:
        raise HTTPException(status_code=403, detail="无权访问此会话")


@router.post("/send", response_model=ChatResponse)
async def send_message(
    data: ChatRequest,
    student_id: str = Depends(get_current_student_id),
):
    _ensure_session_owner(data.session_id, student_id)
    async with _session_operation_guard(data.session_id):
        # 判断是否首次消息
        is_first_message = len(_chat_history.get(data.session_id, [])) == 0

        user_msg = ChatMessage(role="user", content=data.message)
        appended_user_item = _append_message_locked(data.session_id, user_msg, save=False)

        # 首次消息自动命名；如果之前只拿到了规则标题，后续消息会有限重试 LLM。
        _schedule_title_generation(data.session_id, data.message, is_first_message=is_first_message)

        try:
            assistant_kwargs = {
                "message": data.message,
                "session_id": data.session_id,
                "student_id": student_id,
            }
            # Keep legacy monkeypatched call signatures working unless the user
            # explicitly enabled web search for this turn.
            if data.web_search:
                assistant_kwargs["web_search"] = True
            assistant_result = await run_in_threadpool(chat_with_history, **assistant_kwargs)
        except Exception as exc:
            logger.error("Agent处理失败: %s", exc, exc_info=True)
            _remove_message_by_identity(data.session_id, appended_user_item, save=False)
            _save_state()
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "AGENT_ERROR",
                    "message": f"Agent处理失败: {str(exc)}",
                    "session_id": data.session_id,
                },
            ) from exc

        assistant_content = (
            assistant_result.get("content", "") if isinstance(assistant_result, dict) else str(assistant_result)
        )
        assistant_sources = assistant_result.get("sources") if isinstance(assistant_result, dict) else None
        query_trace = assistant_result.get("query_trace") if isinstance(assistant_result, dict) else None
        assistant_route = None
        if isinstance(query_trace, dict):
            for event in reversed(query_trace.get("events", [])):
                event_data = event.get("data") or {}
                assistant_route = event_data.get("route") or event_data.get("final_route")
                if assistant_route:
                    break

        assistant_msg = ChatMessage(
            role="assistant",
            content=assistant_content,
            sources=assistant_sources or None,
            route=assistant_route,
            **_web_search_turn_fields(
                requested=bool(data.web_search),
                used_retrieval=assistant_result.get("used_retrieval") if isinstance(assistant_result, dict) else False,
                query_trace=query_trace,
                sources=assistant_sources,
            ),
            metadata={
                "route": assistant_route,
                "used_retrieval": assistant_result.get("used_retrieval"),
                "web_search": bool(data.web_search),
            }
            if isinstance(assistant_result, dict)
            and (assistant_route or assistant_result.get("used_retrieval") is not None)
            else None,
        )
        with _history_lock(data.session_id):
            _append_message(data.session_id, assistant_msg, save=False)
            _update_session_metadata(data.session_id, assistant_msg.timestamp.isoformat(), save=False)
        _save_state()

        return ChatResponse(message=assistant_msg, session_id=data.session_id)


@router.post("/send/stream")
async def send_message_stream(
    data: ChatStreamRequest,
    student_id: str = Depends(get_current_student_id),
):
    session_id = data.session_id
    message = data.message
    web_search = data.web_search
    _ensure_session_owner(session_id, student_id)

    async def generate() -> AsyncGenerator[str, None]:
        operation_lock = _session_operation_lock(session_id)
        operation_lock_acquired = False
        stop_event = threading.Event()
        worker_thread: threading.Thread | None = None
        await _acquire_threading_lock(operation_lock)
        operation_lock_acquired = True

        try:
            # 判断是否首次消息
            is_first_message = len(_chat_history.get(session_id, [])) == 0

            user_msg = ChatMessage(role="user", content=message)
            _append_message_locked(session_id, user_msg, save=False)

            # 首次消息自动命名；如果之前只拿到了规则标题，后续消息会有限重试 LLM。
            _schedule_title_generation(session_id, message, is_first_message=is_first_message)

            loop = asyncio.get_running_loop()
            queue_items: list[dict | object] = []
            queue_lock = threading.Lock()
            progress_events: list[dict] = []
            progress_events_lock = threading.Lock()
            worker_delta_parts: list[str] = []
            worker_delta_lock = threading.Lock()
            persist_lock = threading.Lock()
            persisted_final = threading.Event()
            _register_active_stream_job(session_id, student_id, stop_event)

            def _event_type(item: dict | object) -> str | None:
                return item.get("type") if isinstance(item, dict) else None

            def _snapshot_worker_delta_text() -> str:
                with worker_delta_lock:
                    return "".join(worker_delta_parts)

            def _drop_one_locked(preferred_types: tuple[str, ...]) -> bool:
                for preferred_type in preferred_types:
                    for index, queued_item in enumerate(queue_items):
                        if _event_type(queued_item) == preferred_type:
                            del queue_items[index]
                            return True
                return False

            def _enqueue(item: dict | object) -> bool:
                """Push one worker event into a bounded cross-thread buffer."""

                if loop.is_closed():
                    return False

                item_type = _event_type(item)
                is_terminal = item is _STREAM_SENTINEL or item_type in {"final", "error"}
                with queue_lock:
                    if len(queue_items) >= _STREAM_QUEUE_MAXSIZE:
                        if is_terminal:
                            if not _drop_one_locked(("progress", "delta")) and queue_items:
                                del queue_items[0]
                            if len(queue_items) >= _STREAM_QUEUE_MAXSIZE:
                                return False
                        elif item_type == "delta":
                            if not _drop_one_locked(("progress",)):
                                return False
                        else:
                            return False
                    queue_items.append(item)

                return True

            async def _dequeue(timeout_seconds: float | None = None) -> dict | object:
                deadline = asyncio.get_running_loop().time() + timeout_seconds if timeout_seconds is not None else None
                while True:
                    with queue_lock:
                        if queue_items:
                            return queue_items.pop(0)

                    if deadline is not None and asyncio.get_running_loop().time() >= deadline:
                        return {
                            "type": "error",
                            "message": "流式生成超时，请稍后重试。",
                            "content": _snapshot_worker_delta_text(),
                        }
                    await asyncio.sleep(_SESSION_LOCK_POLL_SECONDS)

            def _progress_snapshot() -> list[dict]:
                with progress_events_lock:
                    return list(progress_events)

            def _record_progress_event(event: dict) -> dict:
                details = event.get("details") or None
                base_progress_event = {
                    "phase": event.get("phase"),
                    "message": event.get("message", ""),
                    "route": event.get("route"),
                    "tool": event.get("tool"),
                    "stream_id": event.get("stream_id"),
                    "resuming": bool(event.get("resuming", False)),
                    "timestamp": datetime.now().isoformat(),
                }
                progress_event = {
                    **base_progress_event,
                    "details": _compact_progress_details_for_history(details),
                }
                with progress_events_lock:
                    progress_events.append(progress_event)
                return {
                    "type": "progress",
                    **base_progress_event,
                    "details": details,
                }

            def _persist_assistant_message_once(assistant_msg: ChatMessage) -> ChatMessage | None:
                with persist_lock:
                    if persisted_final.is_set():
                        return None
                    with _history_lock(session_id):
                        _append_message(session_id, assistant_msg, save=False)
                        _update_session_metadata(session_id, assistant_msg.timestamp.isoformat(), save=False)
                    _save_state()
                    persisted_final.set()
                    return assistant_msg

            def _final_payload_from_event(event: dict) -> dict | None:
                local_progress_events = _progress_snapshot()
                final_content = event.get("content", "") or _snapshot_worker_delta_text()
                assistant_sources = event.get("sources") or None
                metadata = {
                    "route": event.get("route"),
                    "used_retrieval": event.get("used_retrieval"),
                    "web_search": bool(web_search),
                }
                if event.get("error"):
                    metadata["stream_error"] = event.get("error")
                assistant_msg = ChatMessage(
                    role="assistant",
                    content=final_content,
                    sources=assistant_sources,
                    route=event.get("route"),
                    progress=local_progress_events[-1] if local_progress_events else None,
                    progress_events=local_progress_events or None,
                    **_web_search_turn_fields(
                        requested=bool(web_search),
                        used_retrieval=event.get("used_retrieval"),
                        progress_events=local_progress_events,
                        query_trace=event.get("query_trace") if isinstance(event.get("query_trace"), dict) else None,
                        sources=assistant_sources,
                        error=event.get("error"),
                    ),
                    metadata=metadata,
                )
                saved_message = _persist_assistant_message_once(assistant_msg)
                if saved_message is None:
                    return None
                return {
                    "type": "final",
                    "session_id": session_id,
                    "stream_id": event.get("stream_id"),
                    "route": event.get("route"),
                    "error": event.get("error"),
                    "message": _msg_to_dict(saved_message),
                }

            def _error_final_payload(message_text: str, *, content: str = "", route: str | None = None) -> dict | None:
                local_progress_events = _progress_snapshot()
                metadata = {
                    "web_search": bool(web_search),
                    "stream_error": message_text,
                }
                if route:
                    metadata["route"] = route
                assistant_msg = ChatMessage(
                    role="assistant",
                    content=content or f"⚠️ {message_text}",
                    route=route,
                    progress=local_progress_events[-1] if local_progress_events else None,
                    progress_events=local_progress_events or None,
                    **_web_search_turn_fields(
                        requested=bool(web_search),
                        used_retrieval=False,
                        progress_events=local_progress_events,
                        error=message_text,
                    ),
                    metadata=metadata,
                )
                saved_message = _persist_assistant_message_once(assistant_msg)
                if saved_message is None:
                    return None
                return {
                    "type": "final",
                    "session_id": session_id,
                    "error": message_text,
                    "message": _msg_to_dict(saved_message),
                }

            def _release_operation_lock_from_worker() -> None:
                nonlocal operation_lock_acquired
                if operation_lock_acquired:
                    operation_lock.release()
                    operation_lock_acquired = False

            def worker() -> None:
                try:
                    stream_kwargs = {
                        "message": message,
                        "session_id": session_id,
                        "student_id": student_id,
                    }
                    if web_search:
                        stream_kwargs["web_search"] = True
                    for event in stream_chat_with_history(**stream_kwargs):
                        if not isinstance(event, dict):
                            continue
                        if stop_event.is_set():
                            break
                        event_type = event.get("type")
                        if event_type == "progress":
                            _enqueue(_record_progress_event(event))
                            continue
                        if event_type == "delta":
                            delta = event.get("delta", "")
                            if delta:
                                with worker_delta_lock:
                                    worker_delta_parts.append(str(delta))
                                _enqueue(
                                    {
                                        "type": "delta",
                                        "delta": delta,
                                        "stream_id": event.get("stream_id"),
                                        "resuming": bool(event.get("resuming", False)),
                                    }
                                )
                            continue
                        if event_type == "final":
                            payload = _final_payload_from_event(event)
                            if payload:
                                _enqueue(payload)
                            return
                        if event_type == "error":
                            error_message = event.get("message") or event.get("error") or "发送失败"
                            payload = _error_final_payload(
                                error_message,
                                content=event.get("content") or _snapshot_worker_delta_text(),
                                route=event.get("route"),
                            )
                            if payload:
                                _enqueue(payload)
                            return

                    if stop_event.is_set():
                        payload = _error_final_payload("已停止本次回答。", content="⚠️ 已停止本次回答。")
                    else:
                        payload = _error_final_payload(
                            "流式连接已结束，但未收到完整回答。",
                            content=_snapshot_worker_delta_text(),
                        )
                    if payload:
                        _enqueue(payload)
                except Exception as exc:
                    logger.error("流式响应 worker 失败: %s", exc, exc_info=True)
                    payload = _error_final_payload(
                        f"流式响应失败: {str(exc)}",
                        content=_snapshot_worker_delta_text(),
                    )
                    if payload:
                        _enqueue(payload)
                finally:
                    _enqueue(_STREAM_SENTINEL)
                    _unregister_active_stream_job(session_id)
                    _release_operation_lock_from_worker()

            # Keep the blocking sync generator off asyncio's default executor:
            # ASGI test transports may wait for that executor during response
            # shutdown, while a disconnected SSE client cannot force-stop the
            # underlying worker.  A daemon thread plus stop_event avoids tying
            # request cleanup to an uninterruptible worker.
            worker_thread = threading.Thread(
                target=worker,
                name=f"chat-sse-{session_id[:16]}",
                daemon=True,
            )
            worker_thread.start()

            final_sent = False

            while True:
                event = await _dequeue(_STREAM_IDLE_TIMEOUT_SECONDS)

                if event is _STREAM_SENTINEL:
                    break

                event_type = event.get("type")
                if event_type == "progress":
                    yield _sse(event)
                    continue

                if event_type == "delta":
                    if event.get("delta"):
                        yield _sse(event)
                    continue

                if event_type == "final":
                    final_sent = True
                    yield _sse(event)
                    break

                if event_type == "error":
                    error_message = event.get("message") or event.get("error") or "发送失败"
                    stop_event.set()
                    payload = _error_final_payload(
                        error_message,
                        content=event.get("content") or _snapshot_worker_delta_text(),
                        route=event.get("route"),
                    )
                    if payload:
                        final_sent = True
                        yield _sse(payload)
                    break

            if not final_sent:
                payload = _error_final_payload(
                    "流式连接已结束，但未收到完整回答。",
                    content=_snapshot_worker_delta_text(),
                )
                if payload:
                    yield _sse(payload)
        except (asyncio.CancelledError, GeneratorExit):
            raise
        finally:
            if worker_thread is None and operation_lock_acquired:
                operation_lock.release()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/cancel/{session_id}")
async def cancel_chat_generation(
    session_id: str,
    student_id: str = Depends(get_current_student_id),
):
    _ensure_session_owner(session_id, student_id)
    job = _active_stream_job_for(session_id, student_id)
    if not job:
        return {"cancelled": False, "session_id": session_id}

    job.cancel_event.set()
    return {"cancelled": True, "session_id": session_id}


@router.get("/history/{session_id}", response_model=ChatHistoryResponse)
async def get_chat_history(
    session_id: str,
    student_id: str = Depends(get_current_student_id),
):
    _ensure_session_owner(session_id, student_id)

    raw_messages = _chat_history.get(session_id, [])
    messages = [_msg_from_dict(item) for item in raw_messages]
    return ChatHistoryResponse(
        session_id=session_id,
        messages=messages,
        total=len(messages),
        **_active_stream_pending_fields(session_id, student_id),
    )


@router.delete("/history/{session_id}")
async def clear_chat_history(
    session_id: str,
    student_id: str = Depends(get_current_student_id),
):
    _ensure_session_owner(session_id, student_id)
    with state_lock():
        if session_id in _chat_history:
            del _chat_history[session_id]
            _save_state()
    return {"message": "聊天记录已清空"}
