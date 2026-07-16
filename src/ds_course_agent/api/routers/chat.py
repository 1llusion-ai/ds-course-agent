from ..core_bridge import PROJECT_ROOT
from dotenv import load_dotenv
from pathlib import Path

env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    load_dotenv(env_path, override=True)

import asyncio
import json
import logging
from datetime import datetime
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from ..core_bridge import chat_with_history, stream_chat_with_history
from ..schemas.chat import ChatHistoryResponse, ChatMessage, ChatRequest, ChatResponse
from ..state import DEFAULT_SESSION_TITLE, _chat_history, _save as _save_state, _sessions
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

_title_generation_pending: set[str] = set()
# Backward-compatible test/runtime hook. It now tracks only in-flight title jobs
# rather than "already generated" sessions.
_title_gen_cache = _title_generation_pending


def _extract_response_text(response) -> str:
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


def _append_message(session_id: str, message: ChatMessage, *, save: bool = True) -> None:
    _ensure_session_history(session_id)
    _chat_history[session_id].append(_msg_to_dict(message))
    if save:
        _save_state()


def _update_session_metadata(session_id: str, timestamp: str | None = None, *, save: bool = True) -> None:
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


def _schedule_title_generation(session_id: str, message: str, *, is_first_message: bool) -> None:
    """Generate or retry the session title in the background without blocking replies."""
    if not _should_schedule_title_generation(session_id, message, is_first_message=is_first_message):
        return

    _title_generation_pending.add(session_id)

    async def _bg_generate_title():
        try:
            seed_message = _first_user_message(session_id, message)
            generated_title, source = await _generate_session_title_with_source(seed_message)
            if session_id in _sessions:
                _sessions[session_id]["title"] = generated_title
                _sessions[session_id]["title_source"] = source
                _sessions[session_id]["title_generation_attempts"] = (
                    int(_sessions[session_id].get("title_generation_attempts") or 0) + 1
                )
                _save_state()
        except Exception:
            logger.debug("会话标题生成失败", exc_info=True)
            if session_id in _sessions:
                _sessions[session_id]["title"] = build_fallback_session_title(message)
                _sessions[session_id]["title_source"] = "heuristic"
                _sessions[session_id]["title_generation_attempts"] = (
                    int(_sessions[session_id].get("title_generation_attempts") or 0) + 1
                )
                _save_state()
        finally:
            _title_generation_pending.discard(session_id)

    asyncio.create_task(_bg_generate_title())


def _build_stream_error_message(text: str) -> ChatMessage:
    return ChatMessage(
        role="assistant",
        content=f"⚠️ {text}",
        timestamp=datetime.now(),
    )


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/send", response_model=ChatResponse)
async def send_message(data: ChatRequest):
    # 判断是否首次消息
    is_first_message = len(_chat_history.get(data.session_id, [])) == 0

    user_msg = ChatMessage(role="user", content=data.message)
    _append_message(data.session_id, user_msg, save=False)

    # 首次消息自动命名；如果之前只拿到了规则标题，后续消息会有限重试 LLM。
    _schedule_title_generation(data.session_id, data.message, is_first_message=is_first_message)

    try:
        assistant_result = await run_in_threadpool(
            chat_with_history,
            message=data.message,
            session_id=data.session_id,
            student_id=data.student_id,
        )
    except Exception as exc:
        logger.error("Agent处理失败: %s", exc, exc_info=True)
        _chat_history[data.session_id].pop()
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
            data = event.get("data") or {}
            assistant_route = data.get("route") or data.get("final_route")
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
        } if isinstance(assistant_result, dict) and (assistant_route or assistant_result.get("used_retrieval") is not None) else None,
    )
    _append_message(data.session_id, assistant_msg, save=False)
    _update_session_metadata(data.session_id, assistant_msg.timestamp.isoformat(), save=False)
    _save_state()

    return ChatResponse(message=assistant_msg, session_id=data.session_id)


@router.get("/send/stream")
async def send_message_stream(
    session_id: str,
    message: str,
    student_id: str = "default_student",
):
    # 判断是否首次消息
    is_first_message = len(_chat_history.get(session_id, [])) == 0

    user_msg = ChatMessage(role="user", content=message)
    _append_message(session_id, user_msg, save=False)

    # 首次消息自动命名；如果之前只拿到了规则标题，后续消息会有限重试 LLM。
    _schedule_title_generation(session_id, message, is_first_message=is_first_message)

    async def generate() -> AsyncGenerator[str, None]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict | object] = asyncio.Queue()
        progress_events: list[dict] = []

        def worker():
            try:
                for event in stream_chat_with_history(
                    message=message,
                    session_id=session_id,
                    student_id=student_id,
                ):
                    loop.call_soon_threadsafe(queue.put_nowait, event)
            except Exception as exc:
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    {
                        "type": "error",
                        "message": f"流式响应失败: {str(exc)}",
                    },
                )
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, _STREAM_SENTINEL)

        worker_task = asyncio.create_task(run_in_threadpool(worker))
        final_sent = False

        try:
            while True:
                event = await queue.get()

                if event is _STREAM_SENTINEL:
                    break

                event_type = event.get("type")
                if event_type == "progress":
                    progress_event = {
                        "phase": event.get("phase"),
                        "message": event.get("message", ""),
                        "route": event.get("route"),
                        "tool": event.get("tool"),
                        "stream_id": event.get("stream_id"),
                        "resuming": bool(event.get("resuming", False)),
                        "timestamp": datetime.now().isoformat(),
                    }
                    progress_events.append(progress_event)
                    yield _sse(
                        {
                            "type": "progress",
                            **progress_event,
                        }
                    )
                    continue

                if event_type == "delta":
                    delta = event.get("delta", "")
                    if delta:
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
                    assistant_msg = ChatMessage(
                        role="assistant",
                        content=event.get("content", ""),
                        sources=event.get("sources") or None,
                        route=event.get("route"),
                        progress=progress_events[-1] if progress_events else None,
                        progress_events=progress_events or None,
                        metadata={
                            "route": event.get("route"),
                            "used_retrieval": event.get("used_retrieval"),
                        },
                    )
                    _append_message(session_id, assistant_msg, save=False)
                    _update_session_metadata(session_id, assistant_msg.timestamp.isoformat(), save=False)
                    _save_state()
                    yield _sse(
                        {
                            "type": "final",
                            "session_id": session_id,
                            "stream_id": event.get("stream_id"),
                            "route": event.get("route"),
                            "message": _msg_to_dict(assistant_msg),
                        }
                    )
                    break

                if event_type == "error":
                    assistant_msg = _build_stream_error_message(event.get("message", "发送失败"))
                    _append_message(session_id, assistant_msg, save=False)
                    _update_session_metadata(session_id, assistant_msg.timestamp.isoformat(), save=False)
                    _save_state()
                    yield _sse(
                        {
                            "type": "final",
                            "session_id": session_id,
                            "message": _msg_to_dict(assistant_msg),
                        }
                    )
                    final_sent = True
                    break

            if not final_sent:
                assistant_msg = _build_stream_error_message("流式连接已结束，但未收到完整回答。")
                _append_message(session_id, assistant_msg, save=False)
                _update_session_metadata(session_id, assistant_msg.timestamp.isoformat(), save=False)
                _save_state()
                yield _sse(
                    {
                        "type": "final",
                        "session_id": session_id,
                        "message": _msg_to_dict(assistant_msg),
                    }
                )
        finally:
            await worker_task

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
async def get_chat_history(session_id: str, student_id: str = "default_student"):
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="会话不存在")

    if _sessions[session_id].get("student_id") != student_id:
        raise HTTPException(status_code=403, detail="无权访问此会话")

    raw_messages = _chat_history.get(session_id, [])
    messages = [_msg_from_dict(item) for item in raw_messages]
    return ChatHistoryResponse(
        session_id=session_id,
        messages=messages,
        total=len(messages),
    )


@router.delete("/history/{session_id}")
async def clear_chat_history(session_id: str):
    if session_id in _chat_history:
        del _chat_history[session_id]
        _save_state()
    return {"message": "聊天记录已清空"}
