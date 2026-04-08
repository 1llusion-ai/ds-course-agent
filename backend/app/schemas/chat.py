from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str
    timestamp: Optional[datetime] = None


class ChatRequest(BaseModel):
    message: str
    session_id: str
    student_id: str


class ChatResponse(BaseModel):
    message: ChatMessage
    session_id: str


class ChatHistoryResponse(BaseModel):
    session_id: str
    messages: List[ChatMessage]
