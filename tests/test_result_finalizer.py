"""Contract tests for typed route-result finalization."""

from __future__ import annotations

from ds_course_agent.agent.hooks import HookManager
from ds_course_agent.agent.result_finalizer import finalize_route_result, merge_route_result_facts
from ds_course_agent.agent.routing import (
    ExecutionMode,
    QueryContext,
    RetrievalPolicy,
    RouteDecision,
    RouteExecutionResult,
    RouteFamily,
    RouteIntent,
    RouteState,
)
from ds_course_agent.agent.service import AgentService


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


def test_merge_route_result_facts_projects_sources_and_flags_once() -> None:
    """The terminal projection preserves every fact without duplicate sources."""

    from ds_course_agent.tools._shared import RetrievalTrace

    state = _route_state()
    first = {"reference": "《第1章》"}
    second = {"reference": "《第2章》"}
    result = RouteExecutionResult(
        content="回答",
        family=state.decision.family,
        intent=state.decision.intent,
        execution_mode=state.decision.execution_mode,
        sources=[first],
    )
    retrieval = RetrievalTrace(
        retrieval_attempted=True,
        used_retrieval=True,
        sources=[first, second],
    )

    merged = merge_route_result_facts(result, retrieval, degraded=True)

    assert merged.sources == [first, second]
    assert merged.retrieval_attempted is True
    assert merged.used_retrieval is True
    assert merged.degraded is True


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
                attempted=True,
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
        retrieval_attempted=True,
        used_retrieval=True,
    )

    finalized = finalize_route_result(FakeAgent(), state, original)

    assert finalized.content == "回答（已校验）"
    assert finalized.sources == [
        {"reference": "《第1章》"},
        {"reference": "《第2章》"},
    ]
    assert finalized.used_retrieval is True
    assert finalized.retrieval_attempted is True
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
            _track_retrieval([{"reference": "《第3章》"}], attempted=True, used=True)
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
    assert finalized.retrieval_attempted is True
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
    assert finalized.retrieval_attempted is False
    assert finalized.degraded is True


def test_finalize_route_result_does_not_repeat_unsuccessful_retrieval(monkeypatch) -> None:
    """An attempted empty retrieval is terminal evidence state, not permission to rerun it."""

    import ds_course_agent.tools.course_rag as course_rag

    class ForbiddenCourseRagTool:
        def invoke(self, query: str) -> str:
            raise AssertionError(f"retrieval repeated: {query}")

    class FakeAgent:
        def __init__(self) -> None:
            from ds_course_agent.agent.service import AgentService

            self._retrieval_guard_skip_reason = AgentService._retrieval_guard_skip_reason.__get__(self)
            self._maybe_force_grounded_answer = AgentService._maybe_force_grounded_answer.__get__(self)

        def _get_hooks(self) -> HookManager:
            from ds_course_agent.agent.hooks import RetrievalGuardHook

            return HookManager([RetrievalGuardHook()])

    monkeypatch.setattr(course_rag, "course_rag_tool", ForbiddenCourseRagTool())
    state = _route_state()
    result = RouteExecutionResult(
        content="课程资料中没有找到相关内容。",
        family=state.decision.family,
        intent=state.decision.intent,
        execution_mode=state.decision.execution_mode,
        retrieval_attempted=True,
        used_retrieval=False,
    )

    finalized = finalize_route_result(FakeAgent(), state, result)

    assert finalized.content == result.content
    assert finalized.retrieval_attempted is True
    assert finalized.used_retrieval is False
