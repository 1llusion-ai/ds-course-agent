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


def _route_state() -> RouteState:
    context = QueryContext(
        original_query="什么是过拟合？",
        normalized_query="什么是过拟合",
        session_id="session-finalizer",
        student_id="student-finalizer",
        chat_history=[],
    )
    decision = RouteDecision(
        family=RouteFamily.LEARNING,
        intent=RouteIntent.CONCEPT_QA,
        execution_mode=ExecutionMode.TOOL_AGENT,
        confidence=0.9,
        reasons=["unit-test"],
        retrieval_policy=RetrievalPolicy.REQUIRED,
        allowed_tools=("course_rag_tool",),
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
