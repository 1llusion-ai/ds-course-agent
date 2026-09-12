"""Route handlers for AgentService.

This is a Phase 2 extraction from the monolithic ``AgentService._execute_route``
if/elif block.  Handlers are intentionally small and receive ``agent`` as an
adapter so we can move behavior incrementally without changing QueryPipeline or
skill executor contracts.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any, Protocol

from ds_course_agent.agent.events import TurnEvent
from ds_course_agent.agent.message_context import build_turn_system_context
from ds_course_agent.agent.route_executor import (
    build_route_result,
    build_route_result_event,
    capture_retrieval,
    execute_selected_route_handler,
    observe_stream_end,
)
from ds_course_agent.agent.routing import ExecutionMode, RouteExecutionResult, RouteIntent, RouteState
from ds_course_agent.research.pipeline import WebResearchPipeline
from ds_course_agent.runtime.model_stream import iter_text_chunks

logger = logging.getLogger(__name__)


class RouteHandler(Protocol):
    """Execute one RouteDecision branch in sync or streaming mode."""

    def can_handle(self, agent: Any, route_state: RouteState) -> bool: ...
    def execute(self, agent: Any, route_state: RouteState, *, stream: bool = False) -> RouteExecutionResult: ...
    def stream_execute(self, agent: Any, route_state: RouteState) -> Iterator[str | TurnEvent]: ...


class BufferedRouteHandlerMixin:
    """Default streaming behavior for handlers that only produce buffered text."""

    def stream_execute(self, agent: Any, route_state: RouteState) -> Iterator[str | TurnEvent]:
        # Route-level hooks (notably RetrievalGuardHook) live in the shared
        # result finalizer, so buffered streaming must go
        # through that path rather than calling execute() directly.  Use the
        # already-selected handler to avoid a second first-match dispatch.
        result = execute_selected_route_handler(agent, self, route_state, stream=True)
        yield from iter_text_chunks(result.content)
        yield build_route_result_event(result)


class SpecialCaseRouteHandler(BufferedRouteHandlerMixin):
    def can_handle(self, agent: Any, route_state: RouteState) -> bool:
        return bool(route_state.special_case_response)

    def execute(self, agent: Any, route_state: RouteState, *, stream: bool = False) -> RouteExecutionResult:
        from ds_course_agent.shared.query_trace import trace_step

        trace_step("agent.branch", branch="special_case")
        return build_route_result(route_state, str(route_state.special_case_response))


class CourseScheduleRouteHandler(BufferedRouteHandlerMixin):
    def can_handle(self, agent: Any, route_state: RouteState) -> bool:
        return route_state.decision.intent == RouteIntent.COURSE_SCHEDULE

    def execute(self, agent: Any, route_state: RouteState, *, stream: bool = False) -> RouteExecutionResult:
        from ds_course_agent.shared.query_trace import trace_step
        from ds_course_agent.tools.course_schedule import course_schedule_tool

        question = route_state.context.original_query
        trace_step("agent.branch", branch="schedule")
        result = course_schedule_tool.invoke(agent._build_schedule_tool_query(question))
        return build_route_result(route_state, result)


class CurrentDatetimeRouteHandler(BufferedRouteHandlerMixin):
    def can_handle(self, agent: Any, route_state: RouteState) -> bool:
        return route_state.decision.intent == RouteIntent.CURRENT_DATETIME

    def execute(self, agent: Any, route_state: RouteState, *, stream: bool = False) -> RouteExecutionResult:
        from ds_course_agent.shared.query_trace import trace_step
        from ds_course_agent.tools.datetime_tool import current_datetime_tool

        question = route_state.context.original_query
        trace_step("agent.branch", branch="datetime")
        result = current_datetime_tool.invoke(question)
        return build_route_result(route_state, result)


class AssessmentAssignmentRouteHandler(BufferedRouteHandlerMixin):
    """Invoke the one coarse assessment tool with trusted turn context."""

    def can_handle(self, agent: Any, route_state: RouteState) -> bool:
        return route_state.decision.intent is RouteIntent.ASSESSMENT_ASSIGNMENT

    def execute(self, agent: Any, route_state: RouteState, *, stream: bool = False) -> RouteExecutionResult:
        from ds_course_agent.shared.error_response import build_error_response
        from ds_course_agent.shared.query_trace import trace_error, trace_step
        from ds_course_agent.teaching.assessment_assignment import AssessmentAssignmentPlanner
        from ds_course_agent.tools.assessment import AssessmentAssignmentInput

        trace_step("agent.branch", branch="assessment_assignment")
        request = AssessmentAssignmentPlanner().plan(route_state.matched_concepts, route_state.learner_state)
        registry = agent.tool_registry
        tool = registry.get("assign_assessment_tool").tool
        try:
            summary = tool.invoke(AssessmentAssignmentInput(student_id=route_state.student_id, request=request))
        except Exception as exc:
            trace_error("tool.assign_assessment", exc)
            logger.error("assessment assignment failed: %s", exc)
            return build_route_result(
                route_state,
                build_error_response(
                    "测验创建失败",
                    "暂时无法根据课程资料生成测验，请稍后重试。",
                    retryable=True,
                ),
                degraded=True,
            )
        return build_route_result(
            route_state,
            f"已为你准备好《{summary.title}》，共 {summary.question_count} 题。请到“我的测验”开始作答。",
        )


class GroundedRagRouteHandler:
    def can_handle(self, agent: Any, route_state: RouteState) -> bool:
        return route_state.decision.execution_mode == ExecutionMode.GROUNDED_GENERATION

    def execute(self, agent: Any, route_state: RouteState, *, stream: bool = False) -> RouteExecutionResult:
        from ds_course_agent.shared.query_trace import trace_span, trace_step
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

        content, retrieval = capture_retrieval(invoke)
        return build_route_result(route_state, content, retrieval=retrieval)

    def stream_execute(self, agent: Any, route_state: RouteState) -> Iterator[str | TurnEvent]:
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
        from ds_course_agent.shared.query_trace import trace_span, trace_step
        from ds_course_agent.tools.code_executor import (
            PythonSandbox,
            extract_python_code,
            format_python_execution_answer,
        )

        question = route_state.context.original_query
        trace_step("agent.branch", branch="python_exec")
        code = extract_python_code(question)
        if not code:
            return build_route_result(
                route_state,
                "没有检测到可执行的 Python 代码。请把代码放在 ```python ... ``` 代码块中，或直接发送要运行的代码。",
            )

        with trace_span("execute.python_sandbox"):
            execution_result = PythonSandbox().execute(code)
        return build_route_result(route_state, format_python_execution_answer(code, execution_result))


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
        from ds_course_agent.shared.query_trace import trace_step

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
            return build_route_result(route_state, skill(question, student_id, session_id, "0"))
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
            return build_route_result(route_state, skill(question, learner_state, matched_concepts))
        return build_route_result(route_state, skill(question, student_id, session_id))


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
        from ds_course_agent.shared.query_trace import trace_step

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
        graph_agent = agent.model_runtime.agent_for_tools(list(allowed_tools))
        trace_step(
            "agent.tool_gating",
            family=decision.family.value,
            intent=decision.intent.value,
            allowed_tools=list(allowed_tools),
            policy="allowlist",
        )
        return agent.chat, base_turn_context, False, graph_agent

    def _execute_content(self, agent: Any, route_state: RouteState, *, stream: bool = False) -> str:
        from ds_course_agent.agent.routing import get_postprocessor
        from ds_course_agent.shared.query_trace import trace_span, trace_step

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
        content, retrieval = capture_retrieval(lambda: self._execute_content(agent, route_state, stream=stream))
        return build_route_result(route_state, content, retrieval=retrieval)

    def stream_execute(self, agent: Any, route_state: RouteState) -> Iterator[str | TurnEvent]:
        """Stream generic-agent routes where safe; otherwise return buffered text.

        The direct-stream path intentionally preserves the Phase 2 behavior:
        it is only used for routes that do not require postprocessor buffering
        and do not require retrieval. All other generic routes run through the
        buffered execute(stream=True) path so route-specific postprocessing stays
        centralized in this handler instead of in AgentService.
        """

        from ds_course_agent.shared.query_trace import trace_span

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

            if streamed_any and "".join(streamed_parts).strip():
                observe_stream_end(agent, route_state, "".join(streamed_parts), stream=True)
                return

            return

        result = execute_selected_route_handler(agent, self, route_state, stream=True)
        yield from iter_text_chunks(result.content)
        yield build_route_result_event(result)


def default_route_handlers() -> list[RouteHandler]:
    """Return handlers in first-match order."""

    return [
        SpecialCaseRouteHandler(),
        CourseScheduleRouteHandler(),
        CurrentDatetimeRouteHandler(),
        AssessmentAssignmentRouteHandler(),
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
    "AssessmentAssignmentRouteHandler",
    "GroundedRagRouteHandler",
    "WebSearchRouteHandler",
    "PythonExecRouteHandler",
    "SkillRouteHandler",
    "GenericAgentRouteHandler",
]
