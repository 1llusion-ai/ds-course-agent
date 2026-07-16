"""Agent hook and route-handler infrastructure tests."""

from ds_course_agent.hooks import HookManager, RetrievalGuardHook
from ds_course_agent.rag.query_pipeline import QueryContext, RouteDecision, RouteType


def _route_state(*, route=RouteType.GENERIC_AGENT, retrieval_policy="required"):
    context = QueryContext(
        original_query="什么是过拟合？",
        normalized_query="什么是过拟合",
        session_id="session-hooks",
        student_id="student-hooks",
        chat_history=[],
    )
    decision = RouteDecision(
        route=route,
        confidence=0.9,
        reasons=["unit-test"],
        retrieval_policy=retrieval_policy,
    )
    return {
        "context": context,
        "decision": decision,
        "chat_history": [],
        "student_id": "student-hooks",
        "special_case_response": None,
        "matched_concepts": [],
    }


def test_hook_manager_after_llm_transforms_result_in_order():
    class AddSuffix:
        def __init__(self, suffix):
            self.suffix = suffix

        def after_llm(self, state, result, **kwargs):
            return f"{result}{self.suffix}"

    manager = HookManager([AddSuffix("A"), AddSuffix("B")])

    assert manager.after_llm(_route_state(), "start") == "startAB"


def test_retrieval_guard_hook_forces_answer_and_records_trace(monkeypatch):
    from ds_course_agent.rag.query_trace import begin_query_trace, end_query_trace

    state = _route_state()

    class FakeAgent:
        def _retrieval_guard_skip_reason(self, route_state, result):
            assert route_state is state
            assert result == "ungrounded"
            return None

        def _maybe_force_grounded_answer(self, question, chat_history=None, skip=False):
            assert question == "什么是过拟合？"
            assert skip is False
            return "grounded answer"

    token = begin_query_trace({"entrypoint": "unit_test"})
    result = RetrievalGuardHook().after_llm(state, "ungrounded", agent=FakeAgent())
    trace = end_query_trace(token)

    assert result == "grounded answer"
    assert any(event["stage"] == "retrieval_guard.force" for event in trace["events"])


def test_retrieval_guard_hook_preserves_result_when_skipped():
    state = _route_state(retrieval_policy="optional")

    class FakeAgent:
        def _retrieval_guard_skip_reason(self, route_state, result):
            return "retrieval_policy=optional"

        def _maybe_force_grounded_answer(self, question, chat_history=None, skip=False):
            assert skip is True
            return None

    assert RetrievalGuardHook().after_llm(state, "original", agent=FakeAgent()) == "original"


def test_retrieval_guard_hook_skips_grounded_rag_route_without_agent_callbacks():
    state = _route_state(route=RouteType.GROUNDED_RAG, retrieval_policy="required")

    class FakeAgent:
        def _retrieval_guard_skip_reason(self, route_state, result):
            raise AssertionError("grounded RAG route should skip before guard callbacks")

        def _maybe_force_grounded_answer(self, question, chat_history=None, skip=False):
            raise AssertionError("grounded RAG route should not force a second RAG call")

    assert RetrievalGuardHook().after_llm(state, "grounded", agent=FakeAgent()) == "grounded"


def test_execute_route_dispatches_to_route_handler_without_if_ladder():
    from ds_course_agent.rag.agent import AgentService

    calls = []

    class FakeHandler:
        def can_handle(self, agent, route_state):
            calls.append(("can", route_state["decision"].route.value))
            return True

        def execute(self, agent, route_state, *, stream=False):
            calls.append(("execute", stream))
            return "handled by route handler"

    service = AgentService.__new__(AgentService)
    service.route_handlers = [FakeHandler()]
    service.hooks = HookManager([])

    result = service._execute_route(_route_state(route=RouteType.COURSE_SCHEDULE), stream=True)

    assert result == "handled by route handler"
    assert calls == [("can", "course_schedule"), ("execute", True)]


def test_student_profile_context_is_natural_language_summary():
    from ds_course_agent.rag.agent import AgentService
    from ds_course_agent.rag.profile_models import ConceptFocus, StudentProfile, WeakSpotCandidate

    service = AgentService.__new__(AgentService)
    profile = StudentProfile(student_id="student-hooks")
    profile.recent_concepts["decision_tree"] = ConceptFocus(
        concept_id="decision_tree",
        display_name="决策树",
        chapter="第6章",
        mention_count=3,
        last_mentioned_at=2.0,
    )
    profile.weak_spot_candidates.append(
        WeakSpotCandidate(
            concept_id="feature_selection",
            display_name="特征选择",
            confidence=0.8,
        )
    )

    summary = service._format_student_profile_for_prompt(profile)

    assert "Student Profile Context" in summary
    assert "最近关注概念：决策树（第6章）x3" in summary
    assert "当前薄弱点：特征选择" in summary


def test_generic_route_passes_turn_context_to_chat(monkeypatch):
    from ds_course_agent.rag.route_handlers import GenericAgentRouteHandler

    state = _route_state(route=RouteType.GENERIC_AGENT, retrieval_policy="optional")
    captured = {}

    class FakePostprocessor:
        def process(self, context, decision, result, chat_history=None):
            class Response:
                content = result

            return Response()

    monkeypatch.setattr(
        "ds_course_agent.rag.query_pipeline.get_postprocessor",
        lambda: FakePostprocessor(),
    )

    class FakeAgent:
        def _route_execution_query(self, context, decision):
            return context.original_query

        def _build_turn_system_context(self, route_state):
            assert route_state is state
            return "turn profile context"

        def chat(self, user_input, chat_history=None, stream=False, turn_context=None):
            captured["turn_context"] = turn_context
            return "answer"

    result = GenericAgentRouteHandler().execute(FakeAgent(), state, stream=False)

    assert result == "answer"
    assert captured["turn_context"] == "turn profile context"
