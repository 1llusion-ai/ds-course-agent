from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List


class SessionCreate(BaseModel):
    title: str = Field(default="新会话", min_length=1, max_length=100)
    student_id: str = Field(default="default_student")


class SessionResponse(BaseModel):
    id: str
    title: str
    student_id: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class SessionList(BaseModel):
    sessions: List[SessionResponse]
    total: int


class SessionUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=100)
