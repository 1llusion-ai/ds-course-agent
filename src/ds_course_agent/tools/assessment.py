"""Coarse-grained assessment assignment tool for the teaching agent."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from ds_course_agent.assessment.feedback import AssessmentGenerationProgress
from ds_course_agent.assessment.models import GenerateQuestionsRequest
from ds_course_agent.assessment.preparation import AssessmentPreparation, PreparationOrigin, PreparationStatus
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
    display_name: str | None = None


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

    def enqueue(self, tool_input: AssessmentAssignmentInput) -> AssessmentPreparation:
        """Queue an explicit Agent request and return its durable preparation state."""

        if not isinstance(tool_input, AssessmentAssignmentInput):
            raise TypeError("assign_assessment_tool requires AssessmentAssignmentInput")
        student_id = tool_input.student_id.strip()
        if not student_id:
            raise ValueError("student_id must be non-empty")
        # Injected application fakes used by route tests predate the durable
        # queue interface. Keep that seam synchronous while production uses
        # the process-owned learning loop below.
        if self._service_factory is not None:
            summary = self.invoke(tool_input)
            from time import time

            return AssessmentPreparation(
                id=summary.id,
                student_id=student_id,
                session_id=tool_input.session_id or "explicit",
                display_name=tool_input.display_name or tool_input.request.target_kc_id,
                request=tool_input.request,
                source_event_ids=(),
                plan_context=tool_input.plan_context,
                status=PreparationStatus.READY,
                assessment_id=summary.id,
                updated_at=time(),
                course_id=tool_input.course_id,
                origin=PreparationOrigin.EXPLICIT,
            )

        from ds_course_agent.agent.learning_loop import get_session_learning_loop

        return get_session_learning_loop().enqueue_explicit(
            student_id,
            tool_input.session_id or "explicit",
            tool_input.display_name or tool_input.request.target_kc_id,
            tool_input.request,
            plan_context=tool_input.plan_context,
            course_id=tool_input.course_id,
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
