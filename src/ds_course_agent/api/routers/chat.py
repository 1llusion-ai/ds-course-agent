"""FastAPI route adapters for chat application use cases."""

from __future__ import annotations

from typing import Any

from dotenv import load_dotenv

from ds_course_agent.api.core_bridge import PROJECT_ROOT

env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    load_dotenv(env_path, override=True)

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from ds_course_agent.api import chat_application
from ds_course_agent.api.auth.deps import get_current_student_id
from ds_course_agent.api.schemas.chat import (
    ChatContinueRequest,
    ChatHistoryResponse,
    ChatRequest,
    ChatResponse,
    ChatStreamRequest,
)
from ds_course_agent.api.sse import iter_stream_job_events, streaming_response

router = APIRouter()


@router.post("/send", response_model=ChatResponse)
async def send_message(
    data: ChatRequest,
    student_id: str = Depends(get_current_student_id),
) -> ChatResponse:
    """Execute one non-streaming chat turn."""

    return await chat_application.send_message(data, student_id)


@router.post("/send/stream")
async def send_message_stream(
    data: ChatStreamRequest,
    student_id: str = Depends(get_current_student_id),
) -> StreamingResponse:
    """Start one streaming chat turn."""

    return streaming_response(chat_application.stream_message_events(data, student_id))


@router.post("/continue/stream")
async def continue_message_stream(
    data: ChatContinueRequest,
    student_id: str = Depends(get_current_student_id),
) -> StreamingResponse:
    """Continue the latest stopped assistant response."""

    return streaming_response(chat_application.continue_message_events(data, student_id))


@router.get("/resume/{session_id}")
async def resume_message_stream(
    session_id: str,
    student_id: str = Depends(get_current_student_id),
) -> StreamingResponse:
    """Replay an active or recently completed stream."""

    job = chat_application.get_resume_job(session_id, student_id)
    return streaming_response(iter_stream_job_events(job, include_snapshot=True))


@router.post("/cancel/{session_id}")
async def cancel_chat_generation(
    session_id: str,
    student_id: str = Depends(get_current_student_id),
) -> dict[str, Any]:
    """Request cancellation of the active stream for a session."""

    return chat_application.cancel_generation(session_id, student_id)


@router.get("/history/{session_id}", response_model=ChatHistoryResponse)
async def get_chat_history(
    session_id: str,
    student_id: str = Depends(get_current_student_id),
) -> ChatHistoryResponse:
    """Return persisted chat history and active stream state."""

    return chat_application.get_history(session_id, student_id)


@router.delete("/history/{session_id}")
async def clear_chat_history(
    session_id: str,
    student_id: str = Depends(get_current_student_id),
) -> dict[str, str]:
    """Clear persisted chat history for a session."""

    return chat_application.clear_history(session_id, student_id)
