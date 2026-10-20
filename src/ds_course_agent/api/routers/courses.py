"""Read-only course catalogue API."""

from fastapi import APIRouter

from ds_course_agent.api.course_context import course_catalog

router = APIRouter()


@router.get("")
async def list_courses() -> dict[str, object]:
    """Return safe course identity and readiness metadata for clients."""

    courses = []
    for manifest in course_catalog().list():
        courses.append(
            {
                "course_id": str(manifest.course_id),
                "display_name": manifest.display_name,
                "description": manifest.description,
                "revision": manifest.revision,
                "status": manifest.status,
                "is_ready": manifest.is_ready,
            }
        )
    return {"courses": courses, "total": len(courses)}


__all__ = ["router"]
