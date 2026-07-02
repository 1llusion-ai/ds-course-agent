from __future__ import annotations

from datetime import datetime
import uuid

from fastapi import APIRouter, HTTPException

from ..schemas.session import SessionCreate, SessionList, SessionResponse, SessionUpdate
from ..state import DEFAULT_SESSION_TITLE, _sessions, _save as _save_state, purge_session

router = APIRouter()


def _session_to_response(session_id: str, data: dict) -> SessionResponse:
    return SessionResponse(
        id=session_id,
        title=data.get("title", DEFAULT_SESSION_TITLE),
        student_id=data.get("student_id", "default_student"),
        created_at=(
            datetime.fromisoformat(data["created_at"])
            if isinstance(data.get("created_at"), str)
            else data.get("created_at", datetime.now())
        ),
        updated_at=(
            datetime.fromisoformat(data["updated_at"])
            if isinstance(data.get("updated_at"), str)
            else data.get("updated_at", datetime.now())
        ),
        message_count=data.get("message_count", 0),
    )


@router.post("", response_model=SessionResponse)
async def create_session(data: SessionCreate):
    session_id = str(uuid.uuid4())
    now = datetime.now()

    session_data = {
        "title": data.title,
        "student_id": data.student_id,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "message_count": 0,
    }
    _sessions[session_id] = session_data
    _save_state()

    return _session_to_response(session_id, session_data)


@router.get("", response_model=SessionList)
async def list_sessions(student_id: str = "default_student"):
    sessions = [
        _session_to_response(session_id, session_data)
        for session_id, session_data in _sessions.items()
        if session_data.get("student_id") == student_id
    ]
    sessions.sort(key=lambda session: session.updated_at, reverse=True)
    return SessionList(sessions=sessions, total=len(sessions))


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str, student_id: str = "default_student"):
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="会话不存在")

    if _sessions[session_id].get("student_id") != student_id:
        raise HTTPException(status_code=403, detail="无权访问此会话")

    return _session_to_response(session_id, _sessions[session_id])


@router.delete("/{session_id}")
async def delete_session(session_id: str, student_id: str = "default_student"):
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="会话不存在")

    if _sessions[session_id].get("student_id") != student_id:
        raise HTTPException(status_code=403, detail="无权删除此会话")

    purge_session(session_id)
    return {"message": "会话已删除", "session_id": session_id}


@router.patch("/{session_id}", response_model=SessionResponse)
async def update_session(session_id: str, data: SessionUpdate):
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="会话不存在")

    session = _sessions[session_id]
    if data.title:
        session["title"] = data.title
    session["updated_at"] = datetime.now().isoformat()
    _save_state()

    return _session_to_response(session_id, session)
