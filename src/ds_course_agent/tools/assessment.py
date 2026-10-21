"""Coarse-grained assessment assignment tool for the teaching agent."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from ds_course_agent.assessment.feedback import AssessmentGenerationProgress
from ds_course_agent.assessment.models import GenerateQuestionsRequest
from ds_course_agent.assessment.records import AssessmentSummary
from ds_course_agent.courses.resources import DEFAULT_COURSE_ID, CourseId
from ds_course_agent.teaching.assessment_assignment import AssessmentPlanContext


class AssessmentAssignmentService(Protocol):
    """Application boundary required by the assignment tool."""

    def assign(
        self,
        student_id: str,
        request: GenerateQuestionsRequest,
        *,
        session_id: str | None = None,
        assignment_id: str | None = None,
        generation_progress: AssessmentGenerationProgress | None = None,
        course_id: CourseId | str = DEFAULT_COURSE_ID,
        plan_context: AssessmentPlanContext | None = None,
    ) -> AssessmentSummary:
        """Generate, persist, and assign one assessment."""


@dataclass(frozen=True)
class AssessmentAssignmentInput:
    """Trusted input assembled from the current teaching-agent turn."""

    student_id: str
    request: GenerateQuestionsRequest
    session_id: str | None = None
    assignment_id: str | None = None
    generation_progress: AssessmentGenerationProgress | None = None
    plan_context: AssessmentPlanContext | None = None
    course_id: CourseId = CourseId(DEFAULT_COURSE_ID)


class AssessmentAssignmentTool:
    """Perform the complete side-effecting assessment assignment operation."""

    name = "assign_assessment_tool"

    def __init__(self, service_factory: Callable[[], AssessmentAssignmentService] | None = None) -> None:
        self._service_factory = service_factory

    def invoke(self, tool_input: AssessmentAssignmentInput) -> AssessmentSummary:
        """Assign one assessment using trusted identity and typed generation controls."""

        if not isinstance(tool_input, AssessmentAssignmentInput):
            raise TypeError("assign_assessment_tool requires AssessmentAssignmentInput")
        student_id = tool_input.student_id.strip()
        if not student_id:
            raise ValueError("student_id must be non-empty")
        service = self._service()
        scope = {} if tool_input.course_id == DEFAULT_COURSE_ID else {"course_id": tool_input.course_id}
        if tool_input.plan_context is not None:
            scope["plan_context"] = tool_input.plan_context
        if tool_input.generation_progress is None:
            return service.assign(
                student_id,
                tool_input.request,
                session_id=tool_input.session_id,
                assignment_id=tool_input.assignment_id,
                **scope,
            )
        return service.assign(
            student_id,
            tool_input.request,
            session_id=tool_input.session_id,
            assignment_id=tool_input.assignment_id,
            generation_progress=tool_input.generation_progress,
            **scope,
        )

    def _service(self) -> AssessmentAssignmentService:
        if self._service_factory is not None:
            return self._service_factory()
        from ds_course_agent.assessment.application import get_assessment_application_service

        return get_assessment_application_service()


assign_assessment_tool = AssessmentAssignmentTool()

__all__ = [
    "AssessmentAssignmentInput",
    "AssessmentAssignmentService",
    "AssessmentAssignmentTool",
    "assign_assessment_tool",
]
