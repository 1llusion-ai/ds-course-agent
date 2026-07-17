from ..core_bridge import PROJECT_ROOT
from dotenv import load_dotenv
from pathlib import Path

env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    load_dotenv(env_path, override=True)

import asyncio
import json
import logging
import threading
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from ..core_bridge import chat_with_history, stream_chat_with_history
from ..auth.deps import get_current_student_id
from ..schemas.chat import ChatHistoryResponse, ChatMessage, ChatRequest, ChatResponse
from ..state import DEFAULT_SESSION_TITLE, _chat_history, _save as _save_state, _sessions, state_lock
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

_title_generation_pending: set[str] = set()
# Backward-compatible test/runtime hook. It now tracks only in-flight title jobs
# rather than "already generated" sessions.
_title_gen_cache = _title_generation_pending
_title_generation_tasks: set[asyncio.Task] = set()
_history_locks: dict[str, threading.RLock] = {}
_history_locks_guard = threading.Lock()
_session_operation_locks: dict[str, threading.Lock] = {}
_session_operation_locks_guard = threading.Lock()


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
            _compact_progress_detail_value(item, depth=depth + 1)
            for item in value[:_PROGRESS_DETAIL_LIST_LIMIT]
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
        source = "heuristic" if not cleaned_title or looks_like_unprocessed_question_title(question, cleaned_title) else "llm"
        return title, source
    except Exception as exc:
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
        "metadata": msg.metadata or None,
    }


def _msg_from_dict(data: dict) -> ChatMessage:
    ts = data.get("timestamp")
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts)
    return ChatMessage(
        role=data.get("role", "assistant"),
        content=data.get("content", ""),
        timestamp=ts or datetime.now(),
        sources=data.get("sources"),
        route=data.get("route"),
        progress=data.get("progress"),
        progress_events=data.get("progress_events") or data.get("progressEvents"),
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


def _build_stream_error_message(text: str) -> ChatMessage:
    return ChatMessage(
        role="assistant",
        content=f"⚠️ {text}",
        timestamp=datetime.now(),
    )


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

        assistant_content = assistant_result.get("content", "") if isinstance(assistant_result, dict) else str(assistant_result)
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
            metadata={
                "route": assistant_route,
                "used_retrieval": assistant_result.get("used_retrieval"),
                "web_search": bool(data.web_search),
            } if isinstance(assistant_result, dict) and (assistant_route or assistant_result.get("used_retrieval") is not None) else None,
        )
        with _history_lock(data.session_id):
            _append_message(data.session_id, assistant_msg, save=False)
            _update_session_metadata(data.session_id, assistant_msg.timestamp.isoformat(), save=False)
        _save_state()

        return ChatResponse(message=assistant_msg, session_id=data.session_id)


@router.get("/send/stream")
async def send_message_stream(
    session_id: str,
    message: str,
    web_search: bool = False,
    student_id: str = Depends(get_current_student_id),
):
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
            queue_event = asyncio.Event()
            queue_items: list[dict | object] = []
            queue_lock = threading.Lock()
            progress_events: list[dict] = []
            worker_delta_parts: list[str] = []
            worker_delta_lock = threading.Lock()

            def _event_type(item: dict | object) -> str | None:
                return item.get("type") if isinstance(item, dict) else None

            def _snapshot_worker_delta_text() -> str:
                with worker_delta_lock:
                    return "".join(worker_delta_parts)

            def _wake_consumer() -> None:
                if loop.is_closed():
                    return
                with suppress(RuntimeError):
                    loop.call_soon_threadsafe(queue_event.set)

            def _drop_one_locked(preferred_types: tuple[str, ...]) -> bool:
                for preferred_type in preferred_types:
                    for index, queued_item in enumerate(queue_items):
                        if _event_type(queued_item) == preferred_type:
                            del queue_items[index]
                            return True
                return False

            def _enqueue(item: dict | object) -> bool:
                """Push one worker event into a bounded cross-thread buffer."""

                if stop_event.is_set() or loop.is_closed():
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

                _wake_consumer()
                return True

            async def _dequeue() -> dict | object:
                while True:
                    with queue_lock:
                        if queue_items:
                            return queue_items.pop(0)

                    queue_event.clear()
                    with queue_lock:
                        if queue_items:
                            continue
                    await queue_event.wait()

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
                        if stop_event.is_set():
                            break
                        if isinstance(event, dict) and event.get("type") == "delta":
                            delta = event.get("delta", "")
                            if delta:
                                with worker_delta_lock:
                                    worker_delta_parts.append(str(delta))
                        _enqueue(event)
                except Exception as exc:
                    logger.error("流式响应 worker 失败: %s", exc, exc_info=True)
                    _enqueue(
                        {
                            "type": "error",
                            "message": f"流式响应失败: {str(exc)}",
                            "content": _snapshot_worker_delta_text(),
                        }
                    )
                finally:
                    _enqueue(_STREAM_SENTINEL)

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
            delta_parts: list[str] = []

            while True:
                event = await _dequeue()

                if event is _STREAM_SENTINEL:
                    break

                event_type = event.get("type")
                if event_type == "progress":
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
                    progress_events.append(progress_event)
                    yield _sse(
                        {
                            "type": "progress",
                            **base_progress_event,
                            "details": details,
                        }
                    )
                    continue

                if event_type == "delta":
                    delta = event.get("delta", "")
                    if delta:
                        delta_parts.append(str(delta))
                        yield _sse(
                            {
                                "type": "delta",
                                "delta": delta,
                                "stream_id": event.get("stream_id"),
                                "resuming": bool(event.get("resuming", False)),
                            }
                        )
                    continue

                if event_type == "final":
                    final_sent = True
                    final_content = (
                        event.get("content", "")
                        or _snapshot_worker_delta_text()
                        or "".join(delta_parts)
                    )
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
                        sources=event.get("sources") or None,
                        route=event.get("route"),
                        progress=progress_events[-1] if progress_events else None,
                        progress_events=progress_events or None,
                        metadata=metadata,
                    )
                    with _history_lock(session_id):
                        _append_message(session_id, assistant_msg, save=False)
                        _update_session_metadata(session_id, assistant_msg.timestamp.isoformat(), save=False)
                    _save_state()
                    yield _sse(
                        {
                            "type": "final",
                            "session_id": session_id,
                            "stream_id": event.get("stream_id"),
                            "route": event.get("route"),
                            "error": event.get("error"),
                            "message": _msg_to_dict(assistant_msg),
                        }
                    )
                    break

                if event_type == "error":
                    error_message = event.get("message") or event.get("error") or "发送失败"
                    preserved_content = (
                        event.get("content")
                        or _snapshot_worker_delta_text()
                        or "".join(delta_parts)
                    )
                    metadata = {
                        "web_search": bool(web_search),
                        "stream_error": error_message,
                    }
                    if event.get("route"):
                        metadata["route"] = event.get("route")
                    assistant_msg = ChatMessage(
                        role="assistant",
                        content=preserved_content or f"⚠️ {error_message}",
                        route=event.get("route"),
                        progress=progress_events[-1] if progress_events else None,
                        progress_events=progress_events or None,
                        metadata=metadata,
                    )
                    with _history_lock(session_id):
                        _append_message(session_id, assistant_msg, save=False)
                        _update_session_metadata(session_id, assistant_msg.timestamp.isoformat(), save=False)
                    _save_state()
                    yield _sse(
                        {
                            "type": "final",
                            "session_id": session_id,
                            "error": error_message,
                            "message": _msg_to_dict(assistant_msg),
                        }
                    )
                    final_sent = True
                    break

            if not final_sent:
                error_message = "流式连接已结束，但未收到完整回答。"
                preserved_content = _snapshot_worker_delta_text() or "".join(delta_parts)
                assistant_msg = ChatMessage(
                    role="assistant",
                    content=preserved_content or f"⚠️ {error_message}",
                    progress=progress_events[-1] if progress_events else None,
                    progress_events=progress_events or None,
                    metadata={
                        "web_search": bool(web_search),
                        "stream_error": error_message,
                    },
                )
                with _history_lock(session_id):
                    _append_message(session_id, assistant_msg, save=False)
                    _update_session_metadata(session_id, assistant_msg.timestamp.isoformat(), save=False)
                _save_state()
                yield _sse(
                    {
                        "type": "final",
                        "session_id": session_id,
                        "error": error_message,
                        "message": _msg_to_dict(assistant_msg),
                    }
                )
        except (asyncio.CancelledError, GeneratorExit):
            stop_event.set()
            raise
        finally:
            stop_event.set()
            if operation_lock_acquired:
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
