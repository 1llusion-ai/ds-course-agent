"""Authenticated student HTTP adapter for assigned assessments."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.concurrency import run_in_threadpool

from ds_course_agent.api.auth.deps import get_current_student_id
from ds_course_agent.assessment.application import (
    AssessmentApplicationService,
    AssessmentConcurrencyError,
    AssessmentNotFoundError,
    AssessmentStateError,
    AssessmentSubmissionError,
    get_assessment_application_service,
)
from ds_course_agent.assessment.records import (
    AssessmentResult,
    AssessmentStatus,
    AssessmentSummary,
    StudentAssessment,
    SubmitAssessmentRequest,
)

router = APIRouter()
DEFAULT_VISIBLE_STATUSES = (AssessmentStatus.READY, AssessmentStatus.IN_PROGRESS)


def get_student_assessment_service(
    _student_id: str = Depends(get_current_student_id),
) -> AssessmentApplicationService:
    """Resolve the lifecycle service only after student authentication succeeds."""

    return get_assessment_application_service()


def _parse_statuses(raw_statuses: str) -> tuple[AssessmentStatus, ...]:
    values = [value.strip() for value in raw_statuses.split(",") if value.strip()]
    if not values:
        raise HTTPException(status_code=422, detail="At least one assessment status is required.")
    try:
        statuses = tuple(AssessmentStatus(value) for value in values)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Unknown assessment status.") from exc
    return tuple(dict.fromkeys(statuses))


def _map_lifecycle_error(exc: Exception) -> HTTPException:
    if isinstance(exc, AssessmentNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assessment not found.")
    if isinstance(exc, AssessmentSubmissionError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    if isinstance(exc, AssessmentStateError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, AssessmentConcurrencyError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Assessment changed concurrently; reload and retry.",
        )
    return HTTPException(status_code=500, detail="Assessment operation failed unexpectedly.")


@router.get("", response_model=tuple[AssessmentSummary, ...])
async def list_assessments(
    statuses: str = Query(
        default=",".join(status.value for status in DEFAULT_VISIBLE_STATUSES),
        alias="status",
    ),
    student_id: str = Depends(get_current_student_id),
    service: AssessmentApplicationService = Depends(get_student_assessment_service),
) -> tuple[AssessmentSummary, ...]:
    """List the student's assigned assessments without generation controls."""

    return await run_in_threadpool(service.list_assessments, student_id, _parse_statuses(statuses))


@router.post("/{assessment_id}/open", response_model=StudentAssessment)
async def open_assessment(
    assessment_id: str,
    student_id: str = Depends(get_current_student_id),
    service: AssessmentApplicationService = Depends(get_student_assessment_service),
) -> StudentAssessment:
    """Open an assigned assessment and set its first-open timestamp."""

    try:
        return await run_in_threadpool(service.open, assessment_id, student_id)
    except Exception as exc:
        raise _map_lifecycle_error(exc) from exc


@router.get("/{assessment_id}", response_model=StudentAssessment)
async def get_assessment(
    assessment_id: str,
    student_id: str = Depends(get_current_student_id),
    service: AssessmentApplicationService = Depends(get_student_assessment_service),
) -> StudentAssessment:
    """Return active question text and options without answer material."""

    try:
        return await run_in_threadpool(service.get, assessment_id, student_id)
    except Exception as exc:
        raise _map_lifecycle_error(exc) from exc


@router.post("/{assessment_id}/submit", response_model=AssessmentResult)
async def submit_assessment(
    assessment_id: str,
    request: SubmitAssessmentRequest,
    student_id: str = Depends(get_current_student_id),
    service: AssessmentApplicationService = Depends(get_student_assessment_service),
) -> AssessmentResult:
    """Submit all answers once and return the server-scored result."""

    try:
        return await run_in_threadpool(service.submit, assessment_id, student_id, request.answers)
    except Exception as exc:
        raise _map_lifecycle_error(exc) from exc


@router.get("/{assessment_id}/result", response_model=AssessmentResult)
async def get_assessment_result(
    assessment_id: str,
    student_id: str = Depends(get_current_student_id),
    service: AssessmentApplicationService = Depends(get_student_assessment_service),
) -> AssessmentResult:
    """Return answers, explanations, and textbook sources after submission."""

    try:
        return await run_in_threadpool(service.result, assessment_id, student_id)
    except Exception as exc:
        raise _map_lifecycle_error(exc) from exc
