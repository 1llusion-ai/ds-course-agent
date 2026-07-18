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


class ChatResponse(BaseModel):
    message: ChatMessage
    session_id: str


class ChatHistoryResponse(BaseModel):
    session_id: str
    messages: list[ChatMessage]
    total: int
