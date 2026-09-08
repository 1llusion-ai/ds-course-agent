"""Invariants for the route execution ownership boundary."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ds_course_agent.agent.hooks import HookManager
from ds_course_agent.agent.route_executor import execute_route, iter_route_response, observe_stream_end
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
from ds_course_agent.shared.query_trace import begin_query_trace, end_query_trace


@pytest.fixture
def state() -> RouteState:
    """Use a static route so failures cannot call RAG or a model."""

    return RouteState(
        context=QueryContext(
            original_query="hello", normalized_query="hello", session_id="s", student_id="u", chat_history=[]
        ),
        decision=RouteDecision(
            family=RouteFamily.BOUNDARY,
            intent=RouteIntent.SMALLTALK,
            execution_mode=ExecutionMode.STATIC_RESPONSE,
            confidence=1.0,
            retrieval_policy=RetrievalPolicy.DISABLED,
        ),
        chat_history=[],
        student_id="u",
        session_id="s",
    )


def test_agent_service_does_not_own_route_execution() -> None:
    """No legacy forwarding methods may restore the old ownership boundary."""

    for name in (
        "_get_route_handlers",
        "_select_route_handler",
        "_execute_selected_route_handler",
        "_execute_route",
        "_iter_route_response",
        "_observe_stream_end",
    ):
        assert not hasattr(AgentService, name)


def test_route_result_and_retrieval_capture_have_one_owner() -> None:
    """Handlers and research must not retain duplicate route helpers."""

    import ds_course_agent.agent.handlers as handlers
    import ds_course_agent.research.pipeline as research
    from ds_course_agent.agent.route_executor import build_route_result, capture_retrieval

    assert callable(build_route_result)
    assert callable(capture_retrieval)
    assert not hasattr(handlers, "_route_result")
    assert not hasattr(handlers, "_capture_retrieval")
    assert not hasattr(research, "_route_result")
    assert not hasattr(research, "_capture_retrieval")


@pytest.mark.parametrize("failure_stage", ["selection", "execution"])
@pytest.mark.parametrize("stream", [False, True])
def test_buffered_failures_finalize_once(state, failure_stage, stream) -> None:
    """Both failure stages must pass one typed degraded result through hooks."""

    calls = []

    class Handler:
        def can_handle(self, agent, route_state):
            if failure_stage == "selection":
                raise RuntimeError("selection failed")
            return True

        def execute(self, agent, route_state, *, stream=False):
            raise RuntimeError("execution failed")

    class Hook:
        def after_llm(self, route_state, content, **kwargs):
            calls.append((route_state, content, kwargs["stream"]))
            return "recovered"

    agent = SimpleNamespace(route_handlers=[Handler()], _get_hooks=lambda: HookManager([Hook()]))
    token = begin_query_trace()
    try:
        result = execute_route(agent, state, stream=stream)
    finally:
        trace = end_query_trace(token)
    assert calls == [(state, "", stream)]
    assert result == RouteExecutionResult(
        content="recovered",
        family=state.decision.family,
        intent=state.decision.intent,
        execution_mode=state.decision.execution_mode,
        degraded=True,
    )
    assert trace["errors"][0]["stage"] == ("agent.stream_generate" if stream else "agent.generate")


def test_empty_registry_is_not_replaced_by_default_handlers(state) -> None:
    """An explicitly empty handler registry must remain empty."""

    agent = SimpleNamespace(route_handlers=[], _get_hooks=lambda: HookManager([]))
    result = execute_route(agent, state)
    assert result.degraded is True
    assert agent.route_handlers == []
    with pytest.raises(RuntimeError, match="No route handler available"):
        list(iter_route_response(agent, state))


def test_stream_end_observation_cannot_transform_answer(state) -> None:
    """Post-stream hooks observe text without rewriting already-published content."""

    seen = []

    class Hook:
        def after_stream_end(self, route_state, content, **kwargs):
            seen.append(content)
            return "replacement"

    agent = SimpleNamespace(_get_hooks=lambda: HookManager([Hook()]))
    assert observe_stream_end(agent, state, "published") is None
    assert seen == ["published"]


def test_stream_end_hook_failure_is_traced_and_isolated(state) -> None:
    """Observation failure must not turn a completed stream into a retry."""

    class Hook:
        def after_stream_end(self, route_state, content, **kwargs):
            raise RuntimeError("observer failed")

    agent = SimpleNamespace(_get_hooks=lambda: HookManager([Hook()]))
    token = begin_query_trace()
    try:
        observe_stream_end(agent, state, "published")
    finally:
        trace = end_query_trace(token)
    assert trace["errors"][0]["stage"] == "hook.after_stream_end"
