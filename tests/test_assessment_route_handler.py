"""Assessment assignment route execution tests."""

from __future__ import annotations

from types import SimpleNamespace

from ds_course_agent.agent.handlers import AssessmentAssignmentRouteHandler
from ds_course_agent.agent.routing import (
    ExecutionMode,
    QueryContext,
    RetrievalPolicy,
    RouteDecision,
    RouteFamily,
    RouteIntent,
    RouteState,
)
from ds_course_agent.assessment.records import AssessmentStatus, AssessmentSummary
from ds_course_agent.teaching.learner_state import LearnerStateSnapshot
from ds_course_agent.tools.assessment import AssessmentAssignmentTool
from ds_course_agent.tools.registry import ToolRegistry, ToolSpec


class StubAssignments:
    def __init__(self) -> None:
        self.calls = []

    def assign(self, student_id, request, *, session_id=None, assignment_id=None):
        assert session_id == "session-1"
        self.calls.append((student_id, request))
        return AssessmentSummary.model_validate(
            {
                "id": "assessment-1",
                "title": "决策树测验",
                "status": AssessmentStatus.READY,
                "question_count": 5,
                "assigned_at": "2026-09-12T08:00:00Z",
                "opened_at": None,
            }
        )


def test_handler_assigns_using_planner_without_student_generation_controls() -> None:
    assignments = StubAssignments()
    tool = AssessmentAssignmentTool(lambda: assignments)
    registry = ToolRegistry(
        [
            ToolSpec(
                name=tool.name,
                tool=tool,
                read_only=False,
                side_effect=True,
                concurrency_safe=False,
                expose_to_agent=False,
                exclusive=True,
            )
        ]
    )
    agent = SimpleNamespace(tool_registry=registry)
    context = QueryContext(
        original_query="给我出几道决策树练习题",
        normalized_query="给我出几道决策树练习题",
        session_id="session-1",
        student_id="student-1",
        chat_history=[],
    )
    state = RouteState(
        context=context,
        decision=RouteDecision(
            family=RouteFamily.LEARNING,
            intent=RouteIntent.ASSESSMENT_ASSIGNMENT,
            execution_mode=ExecutionMode.DETERMINISTIC_TOOL,
            confidence=0.96,
            retrieval_policy=RetrievalPolicy.DISABLED,
        ),
        chat_history=[],
        student_id="student-1",
        session_id="session-1",
        learner_state=LearnerStateSnapshot(student_id="student-1"),
        matched_concepts=[SimpleNamespace(concept_id="decision_tree")],
    )

    result = AssessmentAssignmentRouteHandler().execute(agent, state)

    assert assignments.calls[0][0] == "student-1"
    request = assignments.calls[0][1]
    assert request.target_kc_id == "decision_tree"
    assert request.count == 5
    assert "我的测验" in result.content
    assert result.intent is RouteIntent.ASSESSMENT_ASSIGNMENT


def test_handler_returns_assessment_error_without_rag_fallback() -> None:
    class FailingAssignments:
        def assign(self, student_id, request, *, session_id=None, assignment_id=None):
            raise RuntimeError("generation unavailable")

    tool = AssessmentAssignmentTool(FailingAssignments)
    registry = ToolRegistry(
        [
            ToolSpec(
                name=tool.name,
                tool=tool,
                read_only=False,
                side_effect=True,
                concurrency_safe=False,
                expose_to_agent=False,
                exclusive=True,
            )
        ]
    )
    state = RouteState(
        context=QueryContext(
            original_query="给我出几道题",
            normalized_query="给我出几道题",
            session_id="session-1",
            student_id="student-1",
            chat_history=[],
        ),
        decision=RouteDecision(
            family=RouteFamily.LEARNING,
            intent=RouteIntent.ASSESSMENT_ASSIGNMENT,
            execution_mode=ExecutionMode.DETERMINISTIC_TOOL,
            confidence=0.96,
            retrieval_policy=RetrievalPolicy.DISABLED,
        ),
        chat_history=[],
        student_id="student-1",
        session_id="session-1",
    )

    result = AssessmentAssignmentRouteHandler().execute(SimpleNamespace(tool_registry=registry), state)

    assert result.degraded is True
    assert "测验创建失败" in result.content
    assert "基础检索模式" not in result.content
