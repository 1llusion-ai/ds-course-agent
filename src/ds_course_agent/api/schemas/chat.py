from pydantic import BaseModel, Field
from datetime import datetime
from typing import Any, List, Optional, Literal


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)
    sources: Optional[List[dict]] = None
    route: Optional[str] = None
    progress: Optional[dict[str, Any]] = None
    progress_events: Optional[List[dict[str, Any]]] = None
    metadata: Optional[dict[str, Any]] = None


class ChatRequest(BaseModel):
    session_id: str
    message: str = Field(min_length=1, max_length=2000)
    student_id: str = Field(default="default_student")
    stream: bool = False
    web_search: bool = False


class ChatResponse(BaseModel):
    message: ChatMessage
    session_id: str


class ChatHistoryResponse(BaseModel):
    session_id: str
    messages: List[ChatMessage]
    total: int
