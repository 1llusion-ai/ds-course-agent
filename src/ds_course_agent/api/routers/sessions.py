from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from ds_course_agent.api.request_quota import enforce_api_request_quota
from ds_course_agent.api.session_repository import SessionRecord, SQLiteSessionRepository
from ds_course_agent.api.title_generation import DEFAULT_SESSION_TITLE

from ..auth.deps import get_current_student_id
from ..schemas.session import SessionCreate, SessionList, SessionResponse, SessionUpdate

router = APIRouter(dependencies=[Depends(enforce_api_request_quota)])


def _repository() -> SQLiteSessionRepository:
    return SQLiteSessionRepository()


def _session_to_response(record: SessionRecord) -> SessionResponse:
    return SessionResponse(
        id=record.session_id,
        title=record.title,
        student_id=record.student_id,
        created_at=record.created_at,
        updated_at=record.updated_at,
        message_count=record.message_count,
    )


def _owned_session(session_id: str, student_id: str) -> SessionRecord:
    record = _repository().find_session(session_id)
    if record is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if record.student_id != student_id:
        raise HTTPException(status_code=403, detail="无权访问此会话")
    return record


@router.post("", response_model=SessionResponse)
async def create_session(data: SessionCreate, student_id: str = Depends(get_current_student_id)):
    session_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    record = SessionRecord(
        session_id=session_id,
        title=data.title,
        title_source="default" if data.title == DEFAULT_SESSION_TITLE else "manual",
        student_id=student_id,
        created_at=now,
        updated_at=now,
    )
    _repository().create_session(record)
    return _session_to_response(record)


@router.get("", response_model=SessionList)
async def list_sessions(student_id: str = Depends(get_current_student_id)):
    sessions = [_session_to_response(record) for record in _repository().list_sessions(student_id)]
    return SessionList(sessions=sessions, total=len(sessions))


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str, student_id: str = Depends(get_current_student_id)):
    return _session_to_response(_owned_session(session_id, student_id))


@router.delete("/{session_id}")
async def delete_session(session_id: str, student_id: str = Depends(get_current_student_id)):
    _owned_session(session_id, student_id)
    _repository().delete_session(student_id, session_id)
    return {"message": "会话已删除", "session_id": session_id}


@router.patch("/{session_id}", response_model=SessionResponse)
async def update_session(
    session_id: str,
    data: SessionUpdate,
    student_id: str = Depends(get_current_student_id),
):
    record = _owned_session(session_id, student_id)
    updated = replace(
        record,
        title=data.title if data.title is not None else record.title,
        title_source="manual" if data.title is not None else record.title_source,
        updated_at=datetime.now(timezone.utc),
    )
    _repository().save_session(updated)
    return _session_to_response(updated)
