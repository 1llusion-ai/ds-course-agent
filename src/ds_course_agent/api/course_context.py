"""API boundary helpers for validating and constructing course turn context."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException

from ds_course_agent.courses import CourseCatalog, CourseContext, CourseId

DEFAULT_COURSE_ID = "data-science-intro"
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


@lru_cache(maxsize=1)
def course_catalog() -> CourseCatalog:
    return CourseCatalog.from_directory(_PROJECT_ROOT / "data" / "courses")


def normalize_course_id(course_id: str = DEFAULT_COURSE_ID) -> str:
    try:
        return str(CourseId(course_id))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="course_id 格式无效") from exc


def require_course(course_id: str = DEFAULT_COURSE_ID, *, ready: bool = False):
    normalized = normalize_course_id(course_id)
    manifest = course_catalog().get(normalized)
    if manifest is None:
        raise HTTPException(status_code=422, detail=f"未知课程: {normalized}")
    if ready and not manifest.is_ready:
        raise HTTPException(status_code=409, detail=f"课程 {normalized} 的课程资料尚未准备完成")
    return manifest


def build_course_context(
    course_id: str,
    *,
    student_id: str,
    session_id: str,
    ready: bool = True,
) -> CourseContext:
    manifest = require_course(course_id, ready=ready)
    return CourseContext(
        course_id=manifest.course_id,
        resource_revision=manifest.revision,
        student_id=student_id,
        session_id=session_id,
    )


__all__ = ["build_course_context", "course_catalog", "normalize_course_id", "require_course"]
