from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)
    sources: list[dict] | None = None
    route: str | None = None
    progress: dict[str, Any] | None = None
    progress_events: list[dict[str, Any]] | None = None
    web_search_requested: bool = False
    web_search_used: bool = False
    web_search_status: Literal[
        "not_requested",
        "used",
        "blocked_by_scope",
        "no_results",
        "error",
        "not_used",
    ] = "not_requested"
    web_search_reason: str | None = None
    generation_status: Literal["completed", "stopped", "error"] = "completed"
    generation_error: str | None = None
    metadata: dict[str, Any] | None = None


class ChatRequest(BaseModel):
    session_id: str
    message: str = Field(min_length=1, max_length=2000)
    stream: bool = False
    web_search: bool = False


class ChatStreamRequest(BaseModel):
    session_id: str
    message: str = Field(min_length=1, max_length=20000)
    web_search: bool = False


class ChatContinueRequest(BaseModel):
    session_id: str
    message_timestamp: datetime


class ChatResponse(BaseModel):
    message: ChatMessage
    session_id: str


class ActiveStreamSnapshot(BaseModel):
    stream_id: str | None = None
    started_at: datetime
    message_timestamp: datetime
    content: str = ""
    progress: dict[str, Any] | None = None
    progress_events: list[dict[str, Any]] = Field(default_factory=list)
    last_event_id: int = 0


class ChatHistoryResponse(BaseModel):
    session_id: str
    messages: list[ChatMessage]
    total: int
    active_stream: ActiveStreamSnapshot | None = None
