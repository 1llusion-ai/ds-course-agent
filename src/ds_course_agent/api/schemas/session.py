from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from ds_course_agent.courses import CourseId
from ds_course_agent.courses.resources import DEFAULT_COURSE_ID


class SessionCreate(BaseModel):
    title: str = Field(default="新会话", min_length=1, max_length=100)
    course_id: CourseId = CourseId(DEFAULT_COURSE_ID)


class SessionResponse(BaseModel):
    id: str
    title: str
    student_id: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0
    course_id: CourseId = CourseId(DEFAULT_COURSE_ID)


class SessionList(BaseModel):
    sessions: list[SessionResponse]
    total: int


class SessionUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=100)
