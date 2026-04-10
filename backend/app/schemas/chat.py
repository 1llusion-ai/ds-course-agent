from pydantic import BaseModel, Field
from datetime import datetime
from typing import List, Optional, Literal


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)
    sources: Optional[List[dict]] = None


class ChatRequest(BaseModel):
    session_id: str
    message: str = Field(min_length=1, max_length=2000)
    student_id: str = Field(default="default_student")
    stream: bool = False


class ChatResponse(BaseModel):
    message: ChatMessage
    session_id: str


class ChatHistoryResponse(BaseModel):
    session_id: str
    messages: List[ChatMessage]
    total: int
