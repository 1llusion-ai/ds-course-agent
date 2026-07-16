"""Route handlers for AgentService.

This is a Phase 2 extraction from the monolithic ``AgentService._execute_route``
if/elif block.  Handlers are intentionally small and receive ``agent`` as an
adapter so we can move behavior incrementally without changing QueryPipeline or
skill executor contracts.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from ds_course_agent.rag.query_pipeline import RouteType

logger = logging.getLogger(__name__)


class RouteHandler(Protocol):
    """Execute one RouteDecision branch.

    TODO: add a streaming execution contract (`stream_execute` or an
    `execute(stream=True)` iterator return type) so `stream_chat_with_history`
    can delegate route-specific streaming to handlers instead of branching on
    route type itself.
    """

    def can_handle(self, agent: Any, route_state: dict[str, Any]) -> bool: ...
    def execute(self, agent: Any, route_state: dict[str, Any], *, stream: bool = False) -> str: ...


class SpecialCaseRouteHandler:
    def can_handle(self, agent: Any, route_state: dict[str, Any]) -> bool:
        return bool(route_state.get("special_case_response"))

    def execute(self, agent: Any, route_state: dict[str, Any], *, stream: bool = False) -> str:
        from ds_course_agent.rag.query_trace import trace_step

        trace_step("agent.branch", branch="special_case")
        return str(route_state["special_case_response"])


class CourseScheduleRouteHandler:
    def can_handle(self, agent: Any, route_state: dict[str, Any]) -> bool:
        return route_state["decision"].route == RouteType.COURSE_SCHEDULE

    def execute(self, agent: Any, route_state: dict[str, Any], *, stream: bool = False) -> str:
        from ds_course_agent.rag.query_trace import trace_step
        from ds_course_agent.tools.course_schedule import course_schedule_tool

        question = route_state["context"].original_query
        trace_step("agent.branch", branch="schedule")
        result = course_schedule_tool.invoke(agent._build_schedule_tool_query(question))
        return result


class CurrentDatetimeRouteHandler:
    def can_handle(self, agent: Any, route_state: dict[str, Any]) -> bool:
        return route_state["decision"].route == RouteType.CURRENT_DATETIME

    def execute(self, agent: Any, route_state: dict[str, Any], *, stream: bool = False) -> str:
        from ds_course_agent.rag.query_trace import trace_step
        from ds_course_agent.tools.datetime_tool import current_datetime_tool

        question = route_state["context"].original_query
        trace_step("agent.branch", branch="datetime")
        result = current_datetime_tool.invoke(question)
        return result


class GroundedRagRouteHandler:
    def can_handle(self, agent: Any, route_state: dict[str, Any]) -> bool:
        return route_state["decision"].route == RouteType.GROUNDED_RAG

    def execute(self, agent: Any, route_state: dict[str, Any], *, stream: bool = False) -> str:
        from ds_course_agent.rag.query_trace import trace_step, trace_span
        from ds_course_agent.tools.course_rag import course_rag_tool

        context = route_state["context"]
        decision = route_state["decision"]
        execution_query = agent._route_execution_query(context, decision)

        trace_step("agent.branch", branch="grounded_rag_direct")
        # When QueryPipeline has already made a required grounded-RAG decision,
        # avoid a second generic-agent LLM round just to decide whether to call
        # the RAG tool.  The tool still records retrieval/source telemetry.
        with trace_span("execute.grounded_rag_tool"):
            return course_rag_tool.invoke(execution_query)


class PythonExecRouteHandler:
    def can_handle(self, agent: Any, route_state: dict[str, Any]) -> bool:
        return route_state["decision"].route == RouteType.PYTHON_EXEC

    def execute(self, agent: Any, route_state: dict[str, Any], *, stream: bool = False) -> str:
        from ds_course_agent.rag.code_executor import (
            PythonSandbox,
            extract_python_code,
            format_python_execution_answer,
        )
        from ds_course_agent.rag.query_trace import trace_step, trace_span

        question = route_state["context"].original_query
        trace_step("agent.branch", branch="python_exec")
        code = extract_python_code(question)
        if not code:
            return (
                "没有检测到可执行的 Python 代码。"
                "请把代码放在 ```python ... ``` 代码块中，或直接发送要运行的代码。"
            )

        with trace_span("execute.python_sandbox"):
            execution_result = PythonSandbox().execute(code)
        return format_python_execution_answer(code, execution_result)


class SkillRouteHandler:
    _ROUTES = {
        RouteType.CODE_REVIEW: ("code_review_skill", "code_review"),
        RouteType.LEARNING_PATH_SKILL: ("learning_path_skill", "learning_path_skill"),
        RouteType.MISCONCEPTION_SKILL: ("misconception_skill", "misconception_skill"),
        RouteType.PERSONALIZED_EXPLANATION_SKILL: ("explanation_skill", "explanation_skill"),
    }

    def can_handle(self, agent: Any, route_state: dict[str, Any]) -> bool:
        route = route_state["decision"].route
        if route not in self._ROUTES:
            return False
        attr, _branch = self._ROUTES[route]
        return bool(getattr(agent, attr, None))

    def execute(self, agent: Any, route_state: dict[str, Any], *, stream: bool = False) -> str:
        from ds_course_agent.rag.query_trace import trace_step

        context = route_state["context"]
        route = route_state["decision"].route
        student_id = route_state["student_id"]
        session_id = context.session_id
        question = context.original_query
        matched_concepts = route_state.get("matched_concepts") or []
        attr, branch = self._ROUTES[route]
        skill = getattr(agent, attr)

        trace_step("agent.branch", branch=branch)
        if route == RouteType.MISCONCEPTION_SKILL:
            return skill(question, student_id, session_id, "0")
        if route == RouteType.PERSONALIZED_EXPLANATION_SKILL:
            if matched_concepts:
                logger.info(
                    "识别知识点: %s (%s)",
                    matched_concepts[0].concept_id,
                    matched_concepts[0].method,
                )
            return skill(question, student_id, session_id)
        return skill(question, student_id, session_id)


class GenericAgentRouteHandler:
    """Fallback handler for all routes not claimed by earlier handlers."""

    def can_handle(self, agent: Any, route_state: dict[str, Any]) -> bool:
        return True

    def execute(self, agent: Any, route_state: dict[str, Any], *, stream: bool = False) -> str:
        from ds_course_agent.rag.query_pipeline import get_postprocessor
        from ds_course_agent.rag.query_trace import trace_step, trace_span

        context = route_state["context"]
        decision = route_state["decision"]
        chat_history = route_state["chat_history"]
        execution_query = agent._route_execution_query(context, decision)
        turn_context = agent._build_turn_system_context(route_state)

        trace_step("agent.branch", branch="generic_agent")
        if stream:
            with trace_span("execute.agent_chat_stream"):
                streamed_parts = [
                    chunk
                    for chunk in agent.chat(
                        execution_query,
                        chat_history,
                        stream=True,
                        turn_context=turn_context,
                    )
                    if chunk
                ]
            result = "".join(streamed_parts)
            if result == "":
                with trace_span("execute.agent_chat"):
                    result = agent.chat(
                        execution_query,
                        chat_history,
                        stream=False,
                        turn_context=turn_context,
                    )
        else:
            with trace_span("execute.agent_chat"):
                result = agent.chat(
                    execution_query,
                    chat_history,
                    stream=False,
                    turn_context=turn_context,
                )

        if hasattr(result, "__iter__") and not isinstance(result, str):
            result = "".join(result)

        final_response = get_postprocessor().process(
            context,
            decision,
            result,
            chat_history=chat_history,
        )
        return final_response.content


def default_route_handlers() -> list[RouteHandler]:
    """Return handlers in first-match order."""

    return [
        SpecialCaseRouteHandler(),
        CourseScheduleRouteHandler(),
        CurrentDatetimeRouteHandler(),
        GroundedRagRouteHandler(),
        PythonExecRouteHandler(),
        SkillRouteHandler(),
        GenericAgentRouteHandler(),
    ]


__all__ = [
    "RouteHandler",
    "default_route_handlers",
    "SpecialCaseRouteHandler",
    "CourseScheduleRouteHandler",
    "CurrentDatetimeRouteHandler",
    "GroundedRagRouteHandler",
    "PythonExecRouteHandler",
    "SkillRouteHandler",
    "GenericAgentRouteHandler",
]
