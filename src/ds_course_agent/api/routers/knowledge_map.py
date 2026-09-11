"""Authenticated course-map reads, independent of agent and retrieval startup."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from ds_course_agent.api.auth.deps import get_current_student_id
from ds_course_agent.api.core_bridge import get_memory_core
from ds_course_agent.teaching.knowledge_map import KnowledgeMap, get_knowledge_map, overlay_learning_state
from ds_course_agent.teaching.memory_core import MemoryCore

router = APIRouter()


@router.get("", response_model=KnowledgeMap)
async def read_knowledge_map(
    response: Response,
    student_id: str = Depends(get_current_student_id),
    memory: MemoryCore = Depends(get_memory_core),
) -> KnowledgeMap:
    """Return shared course structure with only the signed-in student's state."""
    response.headers["Cache-Control"] = "private, no-store"
    memory.aggregate_profile(student_id)
    return overlay_learning_state(get_knowledge_map(), memory.get_profile(student_id))
