from ds_course_agent.agent.routing import (
    ExecutionMode,
    QueryContext,
    RetrievalPolicy,
    RouteDecision,
    RouteFamily,
    RouteIntent,
)
from ds_course_agent.agent.service import AgentService
from ds_course_agent.courses import CourseContext, CourseId


def _query_context(course_context: CourseContext) -> QueryContext:
    return QueryContext(
        original_query="什么是过拟合？",
        normalized_query="什么是过拟合？",
        session_id="session",
        student_id="student",
        chat_history=[],
        course_context=course_context,
    )


def _decision() -> RouteDecision:
    return RouteDecision(
        family=RouteFamily.LEARNING,
        intent=RouteIntent.CONCEPT_QA,
        execution_mode=ExecutionMode.GROUNDED_GENERATION,
        confidence=0.9,
        retrieval_policy=RetrievalPolicy.REQUIRED,
    )


def test_route_state_keeps_course_contexts_isolated() -> None:
    service = AgentService.__new__(AgentService)
    first = CourseContext(course_id=CourseId("data-science-intro"), resource_revision="revision-a")
    second = CourseContext(course_id=CourseId("digital-literacy"), resource_revision="revision-b")

    first_context = _query_context(first)
    second_context = _query_context(second)
    first_state = service._build_route_state(
        context=first_context,
        decision=_decision(),
        chat_history=[],
        student_id="student",
        session_id="session",
        history=None,
        learner_state=None,
        personalization_context=None,
        matched_concepts=[],
        skill_candidate_keys=set(),
        special_case_response=None,
    )
    second_state = service._build_route_state(
        context=second_context,
        decision=_decision(),
        chat_history=[],
        student_id="student",
        session_id="session",
        history=None,
        learner_state=None,
        personalization_context=None,
        matched_concepts=[],
        skill_candidate_keys=set(),
        special_case_response=None,
    )

    assert first_state.course_context == first
    assert second_state.course_context == second
    assert first_state.context.course_context == first
    assert second_state.context.course_context == second
