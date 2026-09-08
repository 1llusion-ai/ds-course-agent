"""Finalize typed route results after handler execution."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Protocol

from ds_course_agent.agent.hooks.base import HookManager
from ds_course_agent.agent.routing import (
    ExecutionMode,
    RouteExecutionResult,
    RouteFamily,
    RouteState,
)
from ds_course_agent.agent.routing.utils import build_grounded_query_from_history
from ds_course_agent.shared.error_response import build_error_response
from ds_course_agent.tools._shared import (
    RetrievalTrace,
    _track_retrieval,
    begin_retrieval_trace,
    end_retrieval_trace,
    merge_retrieval_sources,
)

logger = logging.getLogger(__name__)


class ResultFinalizerAgent(Protocol):
    """Agent capabilities required by route-result finalization."""

    def _get_hooks(self) -> HookManager: ...


def merge_route_result_facts(
    result: RouteExecutionResult,
    retrieval: RetrievalTrace,
    *,
    degraded: bool = False,
) -> RouteExecutionResult:
    """Project one retrieval trace into the terminal route-result contract."""

    return replace(
        result,
        sources=merge_retrieval_sources(result.sources, retrieval.sources),
        retrieval_attempted=result.retrieval_attempted or retrieval.retrieval_attempted,
        used_retrieval=result.used_retrieval or retrieval.used_retrieval,
        degraded=result.degraded or degraded,
    )


def finalize_route_result(
    agent: ResultFinalizerAgent,
    route_state: RouteState,
    result: RouteExecutionResult,
    *,
    stream: bool = False,
) -> RouteExecutionResult:
    """Apply route hooks, empty-result fallback, and retrieval trace merging."""

    from ds_course_agent.shared.query_trace import trace_error

    user_input = route_state.context.original_query
    chat_history = route_state.chat_history
    content = result.content
    degraded = result.degraded
    token = begin_retrieval_trace()
    _track_retrieval(
        result.sources,
        attempted=result.retrieval_attempted,
        used=result.used_retrieval,
    )

    try:
        content = agent._get_hooks().after_llm(route_state, content, agent=agent, stream=stream)
    except Exception as exc:
        trace_error("hook.after_llm", exc)
        logger.error("after_llm hook failed: %s", exc, exc_info=True)
        if content is None:
            content = ""

    if not content or not isinstance(content, str) or not content.strip():
        degraded = True
        may_ground = route_state.decision.family is RouteFamily.LEARNING and (
            route_state.decision.execution_mode is ExecutionMode.GROUNDED_GENERATION
            or route_state.decision.retrieval_policy == "required"
        )
        if may_ground:
            try:
                from ds_course_agent.tools.course_rag import course_rag_tool

                fallback_query = build_grounded_query_from_history(user_input, chat_history)
                fallback = course_rag_tool.invoke(fallback_query)
                if fallback and fallback.strip() and fallback != "无相关资料":
                    content = f"{fallback}\n\n[注：使用基础检索模式回答]"
                else:
                    content = build_error_response(
                        "无法生成回答",
                        "抱歉，课程资料中暂时没有找到足够内容，或回答服务暂时不可用。",
                        retryable=True,
                    )
            except Exception as exc:
                content = build_error_response(
                    "服务暂时不可用",
                    f"生成回答时遇到错误，请稍后重试。\n({str(exc)[:80]})",
                    retryable=True,
                )
        else:
            content = build_error_response(
                "无法生成回答",
                "本次请求未能生成有效回复，请补充更具体的信息后重试。",
                retryable=True,
            )

    retrieval = end_retrieval_trace(token)
    return merge_route_result_facts(
        replace(result, content=content),
        retrieval,
        degraded=degraded,
    )


__all__ = ["ResultFinalizerAgent", "finalize_route_result", "merge_route_result_facts"]
