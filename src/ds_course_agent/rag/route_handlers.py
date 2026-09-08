"""Route handlers for AgentService.

This is a Phase 2 extraction from the monolithic ``AgentService._execute_route``
if/elif block.  Handlers are intentionally small and receive ``agent`` as an
adapter so we can move behavior incrementally without changing QueryPipeline or
skill executor contracts.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from typing import Any, Protocol, TypeVar

from ds_course_agent.rag.message_context import build_turn_system_context
from ds_course_agent.rag.query_pipeline import ExecutionMode, RouteExecutionResult, RouteIntent, RouteState
from ds_course_agent.rag.turn_events import TurnEvent
from ds_course_agent.rag.web_research import WebResearchPipeline
from ds_course_agent.tools._shared import RetrievalTrace, begin_retrieval_trace, end_retrieval_trace

logger = logging.getLogger(__name__)
_T = TypeVar("_T")


def _route_result(
    route_state: RouteState,
    content: str,
    *,
    retrieval: RetrievalTrace | None = None,
    degraded: bool = False,
) -> RouteExecutionResult:
    """Build the result owned by one route handler execution."""

    decision = route_state.decision
    return RouteExecutionResult(
        content=str(content or ""),
        family=decision.family,
        intent=decision.intent,
        execution_mode=decision.execution_mode,
        sources=list(retrieval.sources) if retrieval else [],
        used_retrieval=bool(retrieval and retrieval.used_retrieval),
        degraded=degraded,
    )


def _capture_retrieval(callback: Callable[[], _T]) -> tuple[_T, RetrievalTrace]:
    """Run one handler body and return retrieval facts recorded by its tools."""

    token = begin_retrieval_trace()
    try:
        result = callback()
    finally:
        retrieval = end_retrieval_trace(token)
    return result, retrieval


class RouteHandler(Protocol):
    """Execute one RouteDecision branch in sync or streaming mode."""

    def can_handle(self, agent: Any, route_state: RouteState) -> bool: ...
    def execute(self, agent: Any, route_state: RouteState, *, stream: bool = False) -> RouteExecutionResult: ...
    def stream_execute(self, agent: Any, route_state: RouteState) -> Iterator[str | TurnEvent]: ...


class BufferedRouteHandlerMixin:
    """Default streaming behavior for handlers that only produce buffered text."""

    def stream_execute(self, agent: Any, route_state: RouteState) -> Iterator[str]:
        # Route-level hooks (notably RetrievalGuardHook) live in
        # AgentService's route finalization, so buffered streaming must go
        # through that path rather than calling execute() directly.  Use the
        # already-selected handler to avoid a second first-match dispatch.
        result = agent._execute_selected_route_handler(self, route_state, stream=True)
        yield from agent._yield_text_chunks(result.content)


class SpecialCaseRouteHandler(BufferedRouteHandlerMixin):
    def can_handle(self, agent: Any, route_state: RouteState) -> bool:
        return bool(route_state.special_case_response)

    def execute(self, agent: Any, route_state: RouteState, *, stream: bool = False) -> RouteExecutionResult:
        from ds_course_agent.rag.query_trace import trace_step

        trace_step("agent.branch", branch="special_case")
        return _route_result(route_state, str(route_state.special_case_response))


class CourseScheduleRouteHandler(BufferedRouteHandlerMixin):
    def can_handle(self, agent: Any, route_state: RouteState) -> bool:
        return route_state.decision.intent == RouteIntent.COURSE_SCHEDULE

    def execute(self, agent: Any, route_state: RouteState, *, stream: bool = False) -> RouteExecutionResult:
        from ds_course_agent.rag.query_trace import trace_step
        from ds_course_agent.tools.course_schedule import course_schedule_tool

        question = route_state.context.original_query
        trace_step("agent.branch", branch="schedule")
        result = course_schedule_tool.invoke(agent._build_schedule_tool_query(question))
        return _route_result(route_state, result)


class CurrentDatetimeRouteHandler(BufferedRouteHandlerMixin):
    def can_handle(self, agent: Any, route_state: RouteState) -> bool:
        return route_state.decision.intent == RouteIntent.CURRENT_DATETIME

    def execute(self, agent: Any, route_state: RouteState, *, stream: bool = False) -> RouteExecutionResult:
        from ds_course_agent.rag.query_trace import trace_step
        from ds_course_agent.tools.datetime_tool import current_datetime_tool

        question = route_state.context.original_query
        trace_step("agent.branch", branch="datetime")
        result = current_datetime_tool.invoke(question)
        return _route_result(route_state, result)


class GroundedRagRouteHandler:
    def can_handle(self, agent: Any, route_state: RouteState) -> bool:
        return route_state.decision.execution_mode == ExecutionMode.GROUNDED_GENERATION

    def execute(self, agent: Any, route_state: RouteState, *, stream: bool = False) -> RouteExecutionResult:
        from ds_course_agent.rag.query_trace import trace_span, trace_step
        from ds_course_agent.tools.course_rag import course_rag_tool

        context = route_state.context
        decision = route_state.decision
        execution_query = agent._route_execution_query(context, decision)

        trace_step("agent.branch", branch="grounded_rag_direct")

        # When QueryPipeline has already made a required grounded-RAG decision,
        # avoid a second generic-agent LLM round just to decide whether to call
        # the RAG tool.  The tool still records retrieval/source telemetry.
        def invoke() -> str:
            with trace_span("execute.grounded_rag_tool"):
                return course_rag_tool.invoke(execution_query)

        content, retrieval = _capture_retrieval(invoke)
        return _route_result(route_state, content, retrieval=retrieval)

    def stream_execute(self, agent: Any, route_state: RouteState) -> Iterator[str]:
        yield from agent._iter_grounded_rag_response(route_state)


class WebSearchRouteHandler:
    """Adapt the explicit web-research route to ``WebResearchPipeline``."""

    def __init__(self, pipeline: WebResearchPipeline | None = None) -> None:
        self._pipeline = pipeline or WebResearchPipeline()

    def can_handle(self, agent: Any, route_state: RouteState) -> bool:
        return route_state.decision.intent == RouteIntent.WEB_RESEARCH

    def execute(
        self,
        agent: Any,
        route_state: RouteState,
        *,
        stream: bool = False,
    ) -> RouteExecutionResult:
        return self._pipeline.execute(agent, route_state, stream=stream)

    def stream_execute(self, agent: Any, route_state: RouteState) -> Iterator[str | TurnEvent]:
        yield from self._pipeline.stream_execute(agent, route_state)


class PythonExecRouteHandler(BufferedRouteHandlerMixin):
    def can_handle(self, agent: Any, route_state: RouteState) -> bool:
        return route_state.decision.execution_mode == ExecutionMode.PYTHON_SANDBOX

    def execute(self, agent: Any, route_state: RouteState, *, stream: bool = False) -> RouteExecutionResult:
        from ds_course_agent.rag.code_executor import (
            PythonSandbox,
            extract_python_code,
            format_python_execution_answer,
        )
        from ds_course_agent.rag.query_trace import trace_span, trace_step

        question = route_state.context.original_query
        trace_step("agent.branch", branch="python_exec")
        code = extract_python_code(question)
        if not code:
            return _route_result(
                route_state,
                "没有检测到可执行的 Python 代码。请把代码放在 ```python ... ``` 代码块中，或直接发送要运行的代码。",
            )

        with trace_span("execute.python_sandbox"):
            execution_result = PythonSandbox().execute(code)
        return _route_result(route_state, format_python_execution_answer(code, execution_result))


class SkillRouteHandler(BufferedRouteHandlerMixin):
    _ROUTES = {
        RouteIntent.CODE_REVIEW: ("code_review_skill", "code_review"),
        RouteIntent.LEARNING_PATH: ("learning_path_skill", "learning_path_skill"),
        RouteIntent.MISCONCEPTION_REPAIR: ("misconception_skill", "misconception_skill"),
        RouteIntent.PERSONALIZED_EXPLANATION: ("explanation_skill", "explanation_skill"),
    }

    def can_handle(self, agent: Any, route_state: RouteState) -> bool:
        intent = route_state.decision.intent
        if intent not in self._ROUTES:
            return False
        attr, _branch = self._ROUTES[intent]
        return bool(getattr(agent, attr, None))

    def execute(self, agent: Any, route_state: RouteState, *, stream: bool = False) -> RouteExecutionResult:
        from ds_course_agent.rag.query_trace import trace_step

        context = route_state.context
        intent = route_state.decision.intent
        student_id = route_state.student_id
        session_id = context.session_id
        question = context.original_query
        matched_concepts = route_state.matched_concepts or []
        attr, branch = self._ROUTES[intent]
        skill = getattr(agent, attr)

        trace_step("agent.branch", branch=branch)
        if intent == RouteIntent.MISCONCEPTION_REPAIR:
            return _route_result(route_state, skill(question, student_id, session_id, "0"))
        if intent in {RouteIntent.LEARNING_PATH, RouteIntent.PERSONALIZED_EXPLANATION}:
            learner_state = route_state.learner_state
            if learner_state is None:
                raise RuntimeError(f"{intent.value} requires learner state enrichment")
            if matched_concepts:
                logger.info(
                    "识别知识点: %s (%s)",
                    matched_concepts[0].concept_id,
                    matched_concepts[0].method,
                )
            return _route_result(route_state, skill(question, learner_state, matched_concepts))
        return _route_result(route_state, skill(question, student_id, session_id))


class GenericAgentRouteHandler:
    """Fallback handler for all routes not claimed by earlier handlers."""

    def can_handle(self, agent: Any, route_state: RouteState) -> bool:
        return True

    def _chat_callable_and_context(
        self,
        agent: Any,
        route_state: RouteState,
        base_turn_context: str,
    ):
        from ds_course_agent.rag.query_trace import trace_step

        decision = route_state.decision
        allowed_tools = decision.allowed_tools

        if decision.execution_mode == ExecutionMode.DIRECT_MODEL:
            trace_step(
                "agent.tool_gating",
                family=decision.family.value,
                intent=decision.intent.value,
                allowed_tools=[],
                policy="none",
            )
            direct_chat = getattr(agent, "direct_chat", None)
            if callable(direct_chat):
                return direct_chat, base_turn_context, True, None
            return agent.chat, base_turn_context, False, None

        if decision.execution_mode != ExecutionMode.TOOL_AGENT:
            raise RuntimeError(f"GenericAgentRouteHandler cannot execute {decision.execution_mode.value}")
        graph_agent = getattr(agent, "_agent_for_tools", lambda _allowed_tools: None)(list(allowed_tools))
        trace_step(
            "agent.tool_gating",
            family=decision.family.value,
            intent=decision.intent.value,
            allowed_tools=list(allowed_tools),
            policy="allowlist",
        )
        return agent.chat, base_turn_context, False, graph_agent

    def _execute_content(self, agent: Any, route_state: RouteState, *, stream: bool = False) -> str:
        from ds_course_agent.rag.query_pipeline import get_postprocessor
        from ds_course_agent.rag.query_trace import trace_span, trace_step

        context = route_state.context
        decision = route_state.decision
        chat_history = route_state.chat_history
        execution_query = agent._route_execution_query(context, decision)
        turn_context = build_turn_system_context(route_state)
        chat_fn, turn_context, direct_llm, graph_agent = self._chat_callable_and_context(
            agent, route_state, turn_context
        )

        trace_step("agent.branch", branch="generic_agent")
        chat_kwargs = {"turn_context": turn_context}
        if graph_agent is not None:
            chat_kwargs["graph_agent"] = graph_agent
        if stream:
            with trace_span("execute.agent_chat_stream", direct_llm=direct_llm):
                streamed_parts = [
                    chunk for chunk in chat_fn(execution_query, chat_history, stream=True, **chat_kwargs) if chunk
                ]
            result = "".join(streamed_parts)
            if result == "":
                with trace_span("execute.agent_chat", direct_llm=direct_llm):
                    result = chat_fn(execution_query, chat_history, stream=False, **chat_kwargs)
        else:
            with trace_span("execute.agent_chat", direct_llm=direct_llm):
                result = chat_fn(execution_query, chat_history, stream=False, **chat_kwargs)

        if hasattr(result, "__iter__") and not isinstance(result, str):
            result = "".join(result)

        final_response = get_postprocessor().process(
            context,
            decision,
            result,
            chat_history=chat_history,
        )
        return final_response.content

    def execute(self, agent: Any, route_state: RouteState, *, stream: bool = False) -> RouteExecutionResult:
        content, retrieval = _capture_retrieval(lambda: self._execute_content(agent, route_state, stream=stream))
        return _route_result(route_state, content, retrieval=retrieval)

    def stream_execute(self, agent: Any, route_state: RouteState) -> Iterator[str]:
        """Stream generic-agent routes where safe; otherwise return buffered text.

        The direct-stream path intentionally preserves the Phase 2 behavior:
        it is only used for routes that do not require postprocessor buffering
        and do not require retrieval. All other generic routes run through the
        buffered execute(stream=True) path so route-specific postprocessing stays
        centralized in this handler instead of in AgentService.
        """

        from ds_course_agent.rag.query_trace import trace_span

        if agent._can_direct_stream_route(route_state):
            context = route_state.context
            decision = route_state.decision
            chat_history = route_state.chat_history
            execution_query = agent._route_execution_query(context, decision)
            turn_context = build_turn_system_context(route_state)
            chat_fn, turn_context, direct_llm, graph_agent = self._chat_callable_and_context(
                agent, route_state, turn_context
            )
            chat_kwargs = {"turn_context": turn_context}
            if graph_agent is not None:
                chat_kwargs["graph_agent"] = graph_agent

            streamed_any = False
            streamed_parts: list[str] = []
            with trace_span("execute.agent_chat_stream", direct_llm=direct_llm):
                for chunk in chat_fn(execution_query, chat_history, stream=True, **chat_kwargs):
                    if chunk:
                        streamed_any = True
                        streamed_parts.append(chunk)
                        yield chunk

            if streamed_any:
                agent._observe_stream_end(route_state, "".join(streamed_parts), stream=True)
                return

            result = agent._execute_selected_route_handler(self, route_state, stream=False)
            yield from agent._yield_text_chunks(result.content)
            return

        result = agent._execute_selected_route_handler(self, route_state, stream=True)
        yield from agent._yield_text_chunks(result.content)


def default_route_handlers() -> list[RouteHandler]:
    """Return handlers in first-match order."""

    return [
        SpecialCaseRouteHandler(),
        CourseScheduleRouteHandler(),
        CurrentDatetimeRouteHandler(),
        GroundedRagRouteHandler(),
        WebSearchRouteHandler(),
        PythonExecRouteHandler(),
        SkillRouteHandler(),
        GenericAgentRouteHandler(),
    ]


__all__ = [
    "RouteHandler",
    "BufferedRouteHandlerMixin",
    "default_route_handlers",
    "SpecialCaseRouteHandler",
    "CourseScheduleRouteHandler",
    "CurrentDatetimeRouteHandler",
    "GroundedRagRouteHandler",
    "WebSearchRouteHandler",
    "PythonExecRouteHandler",
    "SkillRouteHandler",
    "GenericAgentRouteHandler",
]
