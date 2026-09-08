"""Web research pipeline for explicit external-research turns."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from ds_course_agent.agent.events import TurnEvent
from ds_course_agent.agent.result_finalizer import finalize_route_result
from ds_course_agent.agent.route_executor import (
    build_route_result,
    build_route_result_event,
    capture_retrieval,
    observe_stream_end,
)
from ds_course_agent.agent.routing import RouteExecutionResult, RouteState
from ds_course_agent.research.fetch import WebPageFetchPipeline
from ds_course_agent.research.models import PreparedWebAnswer
from ds_course_agent.research.policy import WebResearchPolicy
from ds_course_agent.runtime.model_stream import iter_text_chunks
from ds_course_agent.shared.config_utils import config_bool
from ds_course_agent.shared.error_response import truncate_error


class WebResearchPipeline(WebResearchPolicy):
    """Search, fetch, organize evidence, and generate a web-grounded answer.

    This pipeline runs only after the router selects the explicit web research
    intent. Search results are compacted into evidence cards before the answer
    model sees them, while full source metadata is tracked for the API/UI.
    """

    def __init__(self) -> None:
        self._fetch_pipeline = WebPageFetchPipeline()

    def _prepare_web_answer_context(self, agent: Any, route_state: RouteState) -> PreparedWebAnswer:
        """Search/fetch web evidence and build the LLM turn context once.

        The sync and stream paths share this method so streaming does not have
        to call ``execute(stream=True)`` and buffer the generated tokens before
        yielding them to the frontend.
        """

        from ds_course_agent.shared.query_trace import trace_error, trace_span, trace_step
        from ds_course_agent.tools._shared import _track_retrieval

        context = route_state.context
        question = context.original_query
        chat_history = route_state.chat_history

        trace_step("agent.branch", branch="web_search")
        scope_response = self._web_search_scope_response(question)
        if scope_response:
            trace_step("web_search.scope_blocked", status="blocked", reason="teaching_scope")
            return PreparedWebAnswer(fallback=scope_response)

        _track_retrieval([], attempted=True, used=False)
        try:
            from ds_course_agent.tools.web_search import search_web

            with trace_span("execute.web_search_tool"):
                web_response = self._invoke_search_web(search_web, question)
        except Exception as exc:
            trace_error("execute.web_search_tool", exc)
            return PreparedWebAnswer(
                fallback=(
                    "联网搜索暂时不可用。请稍后重试，或关闭“联网搜索”后继续使用课程资料问答。\n\n"
                    f"（错误信息：{truncate_error(exc)}）"
                ),
                degraded=True,
            )

        sources = self._response_sources(web_response)

        response_error = getattr(web_response, "error", None)
        response_results = self._response_results(web_response)
        if response_error and not response_results:
            trace_step(
                "web_search.no_results",
                status="error",
                provider=str(getattr(web_response, "provider", "") or "").strip(),
                error=truncate_error(response_error),
            )
            return PreparedWebAnswer(
                fallback=(
                    "联网搜索暂时不可用，未获得可用搜索结果。\n\n"
                    f"原因：{response_error}\n\n"
                    "你可以稍后重试，或关闭“联网搜索”后继续使用课程资料问答。"
                ),
                degraded=True,
            )
        if not response_results:
            trace_step(
                "web_search.no_results",
                status="degraded",
                provider=str(getattr(web_response, "provider", "") or "").strip(),
            )
            return PreparedWebAnswer(
                fallback="我已尝试联网搜索，但没有搜索到可用结果。你可以换一个更具体的关键词，或稍后再试。",
                degraded=True,
            )

        evidence_context = self._response_evidence_context(web_response)

        fetch_pages = []
        fetch_context = ""
        try:
            if config_bool("WEB_FETCH_ENABLED", False):
                from ds_course_agent.tools.web_fetch import (
                    compact_fetched_pages,
                    enrich_sources_with_fetch_metadata,
                    fetch_web_pages,
                )

                target_success_count, _max_fetch_attempts, _max_fetch_workers = self._fetch_plan(question)
                fetch_targets = self._candidate_fetch_urls(response_results, question)
                urls = [target["url"] for target in fetch_targets]
                with trace_span("execute.web_fetch_pages", result_count=len(urls)):
                    fetch_pages = fetch_web_pages(
                        urls,
                        top_n=target_success_count,
                        max_attempts=_max_fetch_attempts,
                        max_workers=_max_fetch_workers,
                        total_timeout_seconds=self._fetch_total_timeout_seconds(question),
                    )
                target_by_url = {str(target.get("url") or ""): target for target in fetch_targets if target.get("url")}
                fetch_pages = [
                    self._annotate_fetch_page(
                        page,
                        target_by_url.get(str(getattr(page, "url", "") or ""))
                        or target_by_url.get(str(getattr(page, "final_url", "") or ""))
                        or (fetch_targets[offset] if offset < len(fetch_targets) else None),
                    )
                    for offset, page in enumerate(fetch_pages)
                ]
                fetch_context = compact_fetched_pages(question, fetch_pages)
                if fetch_context:
                    evidence_context = "\n\n".join(
                        part
                        for part in [
                            evidence_context,
                            "# Web Page Reading Evidence\n" + fetch_context,
                        ]
                        if part
                    )
                sources = enrich_sources_with_fetch_metadata(sources, fetch_pages)
                trace_step(
                    "tool.result",
                    tool="web_fetch_tool",
                    status="ok" if fetch_context else "degraded",
                    fetched_count=sum(1 for page in fetch_pages if getattr(page, "ok", False)),
                    attempted_count=len(fetch_pages),
                )
        except Exception as exc:
            # Deep web reading is an enhancement.  Search summaries remain a
            # valid fallback when fetching fails due to anti-bot, parsing, or
            # network constraints.
            trace_error("execute.web_fetch_pages", exc)

        _track_retrieval(
            sources,
            attempted=True,
            used=bool(response_results and str(evidence_context or "").strip()),
        )

        if not evidence_context or not str(evidence_context).strip():
            return PreparedWebAnswer(
                fallback="我已尝试联网搜索，但没有获得可用的搜索摘要。你可以换一个更具体的关键词，或稍后再试。",
                degraded=True,
            )

        web_turn_context = self._build_web_turn_context(
            agent,
            route_state,
            evidence_context=str(evidence_context),
            response_results=response_results,
        )

        return PreparedWebAnswer(
            question=question,
            chat_history=chat_history,
            turn_context=web_turn_context,
        )

    def _execute_content(self, agent: Any, route_state: RouteState, *, stream: bool = False) -> tuple[str, bool]:
        from ds_course_agent.shared.query_trace import trace_span

        prepared = self._prepare_web_answer_context(agent, route_state)
        if prepared.fallback:
            return prepared.fallback, prepared.degraded

        question = prepared.question
        chat_history = prepared.chat_history
        web_turn_context = prepared.turn_context

        chat_fn = agent.direct_chat

        if stream:
            with trace_span("execute.web_search_answer_stream"):
                parts = [
                    chunk
                    for chunk in chat_fn(
                        question,
                        chat_history,
                        stream=True,
                        turn_context=web_turn_context,
                    )
                    if chunk
                ]
            result = "".join(parts)
            if result:
                return result, False

        with trace_span("execute.web_search_answer"):
            result = chat_fn(
                question,
                chat_history,
                stream=False,
                turn_context=web_turn_context,
            )
        if hasattr(result, "__iter__") and not isinstance(result, str):
            result = "".join(result)
        return result, False

    def execute(self, agent: Any, route_state: RouteState, *, stream: bool = False) -> RouteExecutionResult:
        execution, retrieval = capture_retrieval(lambda: self._execute_content(agent, route_state, stream=stream))
        content, degraded = execution
        return build_route_result(route_state, content, retrieval=retrieval, degraded=degraded)

    def stream_execute(self, agent: Any, route_state: RouteState) -> Iterator[str | TurnEvent]:
        from ds_course_agent.shared.query_trace import trace_error, trace_span, trace_step
        from ds_course_agent.tools._shared import _track_retrieval

        context = route_state.context
        question = context.original_query
        chat_history = route_state.chat_history

        trace_step("agent.branch", branch="web_search")

        scope_response = self._web_search_scope_response(question)
        if scope_response:
            trace_step("web_search.scope_blocked", status="blocked", reason="teaching_scope")
            event = self._stream_progress_event(
                route_state,
                "web_search_scope",
                "联网搜索限于教学相关资料",
                tool="web_search_tool",
                details={"query": question, "scope": "teaching"},
            )
            if event:
                yield event
            yield from iter_text_chunks(scope_response)
            return

        event = self._stream_progress_event(
            route_state,
            "web_search_start",
            "联网搜索中",
            tool="web_search_tool",
            details={"query": question},
        )
        if event:
            yield event

        _track_retrieval([], attempted=True, used=False)
        try:
            from ds_course_agent.tools.web_search import search_web

            with trace_span("execute.web_search_tool"):
                web_response = self._invoke_search_web(search_web, question)
        except Exception as exc:
            trace_error("execute.web_search_tool", exc)
            event = self._stream_progress_event(
                route_state,
                "web_search_error",
                "联网搜索暂时不可用",
                tool="web_search_tool",
                details={"query": question, "error": truncate_error(exc)},
            )
            if event:
                yield event
            yield from iter_text_chunks(
                "联网搜索暂时不可用。请稍后重试，或关闭“联网搜索”后继续使用课程资料问答。\n\n"
                f"（错误信息：{truncate_error(exc)}）"
            )
            return

        provider = str(getattr(web_response, "provider", "") or "").strip()
        sources = self._response_sources(web_response)
        response_error = getattr(web_response, "error", None)
        response_results = self._response_results(web_response)
        result_payloads = [
            self._result_progress_payload(result, index) for index, result in enumerate(response_results, start=1)
        ]

        if response_error and not response_results:
            event = self._stream_progress_event(
                route_state,
                "web_search_error",
                "联网搜索未获得可用结果",
                tool="web_search_tool",
                details={
                    "query": question,
                    "provider": provider,
                    "found_count": 0,
                    "error": truncate_error(response_error),
                },
            )
            if event:
                yield event
            yield from iter_text_chunks(
                "联网搜索暂时不可用，未获得可用搜索结果。\n\n"
                f"原因：{response_error}\n\n"
                "你可以稍后重试，或关闭“联网搜索”后继续使用课程资料问答。"
            )
            return

        if not response_results:
            event = self._stream_progress_event(
                route_state,
                "web_search_results",
                "没有搜索到可用网页",
                tool="web_search_tool",
                details={
                    "query": question,
                    "provider": provider,
                    "found_count": 0,
                    "results": [],
                },
            )
            if event:
                yield event
            yield from iter_text_chunks(
                "我已尝试联网搜索，但没有搜索到可用结果。你可以换一个更具体的关键词，或稍后再试。"
            )
            return

        event = self._stream_progress_event(
            route_state,
            "web_search_results",
            f"搜索到 {len(response_results)} 个网页",
            tool="web_search_tool",
            details={
                "query": question,
                "provider": provider,
                "found_count": len(response_results),
                "results": result_payloads,
            },
        )
        if event:
            yield event

        fetch_result = yield from self._fetch_pipeline.stream_fetch_context(
            route_state,
            question=question,
            response_results=response_results,
            sources=sources,
            evidence_context=self._response_evidence_context(web_response),
        )
        sources = fetch_result.sources
        evidence_context = fetch_result.evidence_context
        attempted_fetch_count = fetch_result.attempted_fetch_count
        fetched_count = fetch_result.fetched_count

        _track_retrieval(
            sources,
            attempted=True,
            used=bool(response_results and str(evidence_context or "").strip()),
        )

        if not evidence_context or not str(evidence_context).strip():
            event = self._stream_progress_event(
                route_state,
                "web_search_error",
                "联网搜索没有获得可用摘要",
                tool="web_search_tool",
                details={"query": question, "provider": provider, "found_count": len(response_results)},
            )
            if event:
                yield event
            yield from iter_text_chunks(
                "我已尝试联网搜索，但没有获得可用的搜索摘要。你可以换一个更具体的关键词，或稍后再试。"
            )
            return

        web_turn_context = self._build_web_turn_context(
            agent,
            route_state,
            evidence_context=str(evidence_context),
            response_results=response_results,
        )

        event = self._stream_progress_event(
            route_state,
            "web_answer_start",
            "生成回答中",
            tool="web_search_tool",
            details={
                "query": question,
                "provider": provider,
                "found_count": len(response_results),
                "attempted_count": attempted_fetch_count,
                "fetched_count": fetched_count,
                "results": result_payloads,
            },
        )
        if event:
            yield event

        chat_fn = agent.direct_chat
        streamed_parts: list[str] = []
        with trace_span("execute.web_search_answer_stream"):
            for chunk in chat_fn(
                question,
                chat_history,
                stream=True,
                turn_context=web_turn_context,
            ):
                if chunk:
                    text = str(chunk)
                    streamed_parts.append(text)
                    yield text

        if streamed_parts:
            observe_stream_end(agent, route_state, "".join(streamed_parts), stream=True)
            return

        with trace_span("execute.web_search_answer"):
            result = chat_fn(
                question,
                chat_history,
                stream=False,
                turn_context=web_turn_context,
            )
        if hasattr(result, "__iter__") and not isinstance(result, str):
            result = "".join(result)
        finalized = finalize_route_result(agent, route_state, build_route_result(route_state, result), stream=True)
        yield from iter_text_chunks(finalized.content)
        yield build_route_result_event(finalized)


__all__ = ["WebResearchPipeline"]
