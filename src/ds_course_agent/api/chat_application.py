"""Application service for chat send, stream, continuation, and history use cases."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool

from ds_course_agent.api import chat_sessions, chat_streaming
from ds_course_agent.api.core_bridge import chat_with_history, stream_chat_with_history, stream_continue_with_history
from ds_course_agent.api.schemas.chat import (
    ChatContinueRequest,
    ChatHistoryResponse,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ChatStreamRequest,
)
from ds_course_agent.api.sse import iter_stream_job_events
from ds_course_agent.api.stream_jobs import ActiveStreamJob, stream_job_registry

logger = logging.getLogger(__name__)


async def send_message(data: ChatRequest, student_id: str) -> ChatResponse:
    """Execute and persist one non-streaming chat turn."""

    chat_sessions.ensure_session_owner(data.session_id, student_id)
    async with chat_sessions.session_operation_guard(data.session_id):
        is_first_message = chat_sessions.message_count(data.session_id) == 0
        user_msg = ChatMessage(role="user", content=data.message)
        appended_user_item = chat_sessions.append_message_locked(data.session_id, user_msg, save=False)
        chat_sessions.schedule_title_generation(
            data.session_id,
            data.message,
            is_first_message=is_first_message,
        )

        try:
            assistant_kwargs: dict[str, Any] = {
                "message": data.message,
                "session_id": data.session_id,
                "student_id": student_id,
            }
            if data.web_search:
                assistant_kwargs["web_search"] = True
            assistant_result = await run_in_threadpool(chat_with_history, **assistant_kwargs)
        except Exception as exc:
            logger.error("Agent处理失败: %s", exc, exc_info=True)
            chat_sessions.remove_message_by_identity(data.session_id, appended_user_item, save=False)
            chat_sessions.save_state()
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "AGENT_ERROR",
                    "message": f"Agent处理失败: {str(exc)}",
                    "session_id": data.session_id,
                },
            ) from exc

        assistant_payload = assistant_result if isinstance(assistant_result, dict) else {}
        assistant_content = assistant_payload.get("content", "") if assistant_payload else str(assistant_result)
        assistant_sources = assistant_payload.get("sources")
        query_trace = assistant_payload.get("query_trace")
        assistant_family = assistant_payload.get("family")
        assistant_intent = assistant_payload.get("intent")
        assistant_execution_mode = assistant_payload.get("execution_mode")

        assistant_msg = ChatMessage(
            role="assistant",
            content=assistant_content,
            sources=assistant_sources or None,
            family=assistant_family,
            intent=assistant_intent,
            execution_mode=assistant_execution_mode,
            retrieval_attempted=bool(assistant_payload.get("retrieval_attempted", False)),
            used_retrieval=bool(assistant_payload.get("used_retrieval", False)),
            degraded=bool(assistant_payload.get("degraded", False)),
            **chat_streaming.web_search_turn_fields(
                requested=bool(data.web_search),
                used_retrieval=assistant_payload.get("used_retrieval", False),
                query_trace=query_trace,
                sources=assistant_sources,
            ),
            metadata={
                "web_search": bool(data.web_search),
            }
            if assistant_payload
            else None,
        )
        chat_sessions.append_message_locked(data.session_id, assistant_msg, save=False)
        chat_sessions.update_session_metadata(
            data.session_id,
            assistant_msg.timestamp.isoformat(),
            save=False,
        )
        chat_sessions.save_state()
        return ChatResponse(message=assistant_msg, session_id=data.session_id)


def stream_message_events(
    data: ChatStreamRequest,
    student_id: str,
) -> AsyncGenerator[dict[str, Any], None]:
    """Validate stream ownership before returning the lazy event generator."""

    chat_sessions.ensure_session_owner(data.session_id, student_id)
    return _stream_message_events(data, student_id)


async def _stream_message_events(
    data: ChatStreamRequest,
    student_id: str,
) -> AsyncGenerator[dict[str, Any], None]:
    session_id = data.session_id
    operation_lock = chat_sessions.session_operation_lock(session_id)
    operation_lock_acquired = False
    await chat_sessions.acquire_threading_lock(operation_lock)
    operation_lock_acquired = True

    try:
        is_first_message = chat_sessions.message_count(session_id) == 0
        user_message = ChatMessage(role="user", content=data.message)
        chat_sessions.append_message_locked(session_id, user_message, save=False)
        chat_sessions.schedule_title_generation(
            session_id,
            data.message,
            is_first_message=is_first_message,
        )

        def event_source():
            stream_kwargs: dict[str, Any] = {
                "message": data.message,
                "session_id": session_id,
                "student_id": student_id,
            }
            if data.web_search:
                stream_kwargs["web_search"] = True
            return stream_chat_with_history(**stream_kwargs)

        job = chat_streaming.launch_stream_worker(
            session_id=session_id,
            student_id=student_id,
            operation_lock=operation_lock,
            event_source=event_source,
            message_timestamp=datetime.now(),
            web_search=bool(data.web_search),
        )
        operation_lock_acquired = False
        async for event in iter_stream_job_events(job, include_snapshot=False):
            yield event
    except (asyncio.CancelledError, GeneratorExit):
        raise
    finally:
        if operation_lock_acquired:
            operation_lock.release()


def continue_message_events(
    data: ChatContinueRequest,
    student_id: str,
) -> AsyncGenerator[dict[str, Any], None]:
    """Validate continuation ownership before returning the lazy event generator."""

    chat_sessions.ensure_session_owner(data.session_id, student_id)
    return _continue_message_events(data, student_id)


async def _continue_message_events(
    data: ChatContinueRequest,
    student_id: str,
) -> AsyncGenerator[dict[str, Any], None]:
    session_id = data.session_id
    operation_lock = chat_sessions.session_operation_lock(session_id)
    operation_lock_acquired = False
    await chat_sessions.acquire_threading_lock(operation_lock)
    operation_lock_acquired = True

    try:
        target_item = chat_sessions.find_stopped_assistant_turn(session_id, data.message_timestamp)
        base_message = chat_sessions.message_from_dict(target_item)

        def event_source():
            return stream_continue_with_history(
                partial_content=base_message.content,
                session_id=session_id,
                student_id=student_id,
            )

        job = chat_streaming.launch_stream_worker(
            session_id=session_id,
            student_id=student_id,
            operation_lock=operation_lock,
            event_source=event_source,
            message_timestamp=base_message.timestamp,
            web_search=base_message.web_search_requested,
            initial_content=base_message.content,
            initial_progress_events=base_message.progress_events,
            replace_message_item=target_item,
            base_message=base_message,
        )
        operation_lock_acquired = False
        async for event in iter_stream_job_events(job, include_snapshot=False):
            yield event
    except (asyncio.CancelledError, GeneratorExit):
        raise
    finally:
        if operation_lock_acquired:
            operation_lock.release()


def get_resume_job(session_id: str, student_id: str) -> ActiveStreamJob:
    """Return the owned active or recently completed stream job for replay."""

    chat_sessions.ensure_session_owner(session_id, student_id)
    job = stream_job_registry.get_for_owner(session_id, student_id)
    if not job:
        raise HTTPException(status_code=404, detail="当前会话没有可恢复的生成流")
    return job


def cancel_generation(session_id: str, student_id: str) -> dict[str, Any]:
    """Request cancellation for the student's active generation."""

    chat_sessions.ensure_session_owner(session_id, student_id)
    job = stream_job_registry.get_for_owner(session_id, student_id, active_only=True)
    if not job:
        return {"cancelled": False, "session_id": session_id}
    job.cancel_event.set()
    return {"cancelled": True, "session_id": session_id}


def get_history(session_id: str, student_id: str) -> ChatHistoryResponse:
    """Return persisted messages plus any active stream snapshot."""

    chat_sessions.ensure_session_owner(session_id, student_id)
    raw_messages = chat_sessions.list_messages(session_id)
    messages = [chat_sessions.message_from_dict(item) for item in raw_messages]
    return ChatHistoryResponse(
        session_id=session_id,
        messages=messages,
        total=len(messages),
        active_stream=chat_streaming.active_stream_snapshot(session_id, student_id),
    )


async def clear_history(session_id: str, student_id: str) -> dict[str, str]:
    """Delete persisted messages after any active turn for the session finishes."""

    chat_sessions.ensure_session_owner(session_id, student_id)
    async with chat_sessions.session_operation_guard(session_id):
        chat_sessions.clear_messages(session_id)
    return {"message": "聊天记录已清空"}


__all__ = [
    "cancel_generation",
    "clear_history",
    "continue_message_events",
    "get_history",
    "get_resume_job",
    "send_message",
    "stream_message_events",
]
