"""Contract tests for typed route-result finalization."""

from __future__ import annotations

from ds_course_agent.hooks import HookManager
from ds_course_agent.rag.agent import AgentService
from ds_course_agent.rag.query_pipeline import (
    ExecutionMode,
    QueryContext,
    RetrievalPolicy,
    RouteDecision,
    RouteExecutionResult,
    RouteFamily,
    RouteIntent,
    RouteState,
)
from ds_course_agent.rag.result_finalizer import finalize_route_result


def _route_state(
    *,
    family: RouteFamily = RouteFamily.LEARNING,
    execution_mode: ExecutionMode = ExecutionMode.TOOL_AGENT,
    retrieval_policy: RetrievalPolicy = RetrievalPolicy.REQUIRED,
) -> RouteState:
    context = QueryContext(
        original_query="什么是过拟合？",
        normalized_query="什么是过拟合",
        session_id="session-finalizer",
        student_id="student-finalizer",
        chat_history=[],
    )
    decision = RouteDecision(
        family=family,
        intent=RouteIntent.CONCEPT_QA,
        execution_mode=execution_mode,
        confidence=0.9,
        reasons=["unit-test"],
        retrieval_policy=retrieval_policy,
        allowed_tools=("course_rag_tool",) if execution_mode is ExecutionMode.TOOL_AGENT else (),
    )
    return RouteState(
        context=context,
        decision=decision,
        chat_history=[],
        student_id="student-finalizer",
        session_id="session-finalizer",
        history=None,
        learner_state=None,
        matched_concepts=[],
        skill_candidate_keys=set(),
        special_case_response=None,
    )


def test_agent_service_does_not_retain_result_finalizer_method() -> None:
    """The extracted finalizer must have one implementation owner."""

    assert not hasattr(AgentService, "_finalize_route_result")


def test_finalize_route_result_merges_hook_retrieval_without_duplicate_sources() -> None:
    """Hook retrieval facts must augment, not replace, handler-owned facts."""

    from ds_course_agent.tools._shared import _track_retrieval

    class RetrievalHook:
        def after_llm(self, state, result, **kwargs):
            _track_retrieval(
                [
                    {"reference": "《第1章》"},
                    {"reference": "《第2章》"},
                ],
                used=True,
            )
            return f"{result}（已校验）"

    class FakeAgent:
        def __init__(self) -> None:
            self.hooks = HookManager([RetrievalHook()])

        def _get_hooks(self) -> HookManager:
            return self.hooks

    state = _route_state()
    original = RouteExecutionResult(
        content="回答",
        family=state.decision.family,
        intent=state.decision.intent,
        execution_mode=state.decision.execution_mode,
        sources=[{"reference": "《第1章》"}],
        used_retrieval=True,
    )

    finalized = finalize_route_result(FakeAgent(), state, original)

    assert finalized.content == "回答（已校验）"
    assert finalized.sources == [
        {"reference": "《第1章》"},
        {"reference": "《第2章》"},
    ]
    assert finalized.used_retrieval is True
    assert original.content == "回答"
    assert original.sources == [{"reference": "《第1章》"}]


def test_finalize_route_result_grounds_empty_required_learning_result_once(monkeypatch) -> None:
    """Eligible empty results must use one grounded fallback and merge its trace."""

    import ds_course_agent.tools.course_rag as course_rag
    from ds_course_agent.tools._shared import _track_retrieval

    calls: list[str] = []

    class FakeCourseRagTool:
        def invoke(self, query: str) -> str:
            calls.append(query)
            _track_retrieval([{"reference": "《第3章》"}], used=True)
            return "基础检索回答"

    class FakeAgent:
        def _get_hooks(self) -> HookManager:
            return HookManager([])

    monkeypatch.setattr(course_rag, "course_rag_tool", FakeCourseRagTool())
    state = _route_state()
    empty_result = RouteExecutionResult(
        content="",
        family=state.decision.family,
        intent=state.decision.intent,
        execution_mode=state.decision.execution_mode,
    )

    finalized = finalize_route_result(FakeAgent(), state, empty_result)

    assert calls == ["什么是过拟合？"]
    assert finalized.content == "基础检索回答\n\n[注：使用基础检索模式回答]"
    assert finalized.sources == [{"reference": "《第3章》"}]
    assert finalized.used_retrieval is True
    assert finalized.degraded is True


def test_finalize_route_result_does_not_ground_empty_non_learning_result(monkeypatch) -> None:
    """Boundary and service routes must not gain an implicit RAG branch."""

    import ds_course_agent.tools.course_rag as course_rag

    class ForbiddenCourseRagTool:
        def invoke(self, query: str) -> str:
            raise AssertionError(f"unexpected retrieval: {query}")

    class FakeAgent:
        def _get_hooks(self) -> HookManager:
            return HookManager([])

    monkeypatch.setattr(course_rag, "course_rag_tool", ForbiddenCourseRagTool())
    state = _route_state(
        family=RouteFamily.COURSE_SERVICE,
        execution_mode=ExecutionMode.DETERMINISTIC_TOOL,
        retrieval_policy=RetrievalPolicy.DISABLED,
    )
    empty_result = RouteExecutionResult(
        content="",
        family=state.decision.family,
        intent=state.decision.intent,
        execution_mode=state.decision.execution_mode,
    )

    finalized = finalize_route_result(FakeAgent(), state, empty_result)

    assert "无法生成回答" in finalized.content
    assert finalized.sources == []
    assert finalized.used_retrieval is False
    assert finalized.degraded is True
