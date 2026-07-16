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
