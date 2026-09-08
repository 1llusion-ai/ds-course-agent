"""Concurrent page-fetch stage for streaming web research."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from ds_course_agent.rag.query_pipeline import RouteState
from ds_course_agent.rag.turn_events import TurnEvent
from ds_course_agent.rag.web_research_models import WebFetchContext
from ds_course_agent.rag.web_research_policy import WebResearchPolicy
from ds_course_agent.shared.config_utils import config_bool
from ds_course_agent.shared.error_response import truncate_error


class WebPageFetchPipeline(WebResearchPolicy):
    """Fetch readable pages and emit typed progress events."""

    def stream_fetch_context(
        self,
        route_state: RouteState,
        *,
        question: str,
        response_results: list[Any],
        sources: list[dict[str, Any]],
        evidence_context: str,
    ) -> Generator[TurnEvent, None, WebFetchContext]:
        """Yield web-fetch progress events and return enriched context metadata."""

        from ds_course_agent.rag.query_trace import trace_error, trace_span, trace_step

        fetch_pages: list[Any] = []
        attempted_fetch_count = 0
        fetched_count = 0

        try:
            if config_bool("WEB_FETCH_ENABLED", False):
                from ds_course_agent.tools.web_fetch import (
                    compact_fetched_pages,
                    enrich_sources_with_fetch_metadata,
                    fetch_web_page,
                )

                target_success_count, max_fetch_attempts, max_fetch_workers = self._fetch_plan(question)
                fetch_targets = self._candidate_fetch_urls(response_results, question)
                event = self._stream_progress_event(
                    route_state,
                    "web_fetch_start",
                    ("正在浏览页面" if target_success_count and fetch_targets else "使用搜索摘要生成回答"),
                    tool="web_fetch_tool",
                    details={
                        "query": question,
                        "target_success_count": target_success_count,
                        "max_attempts": min(max_fetch_attempts, len(fetch_targets)),
                        "candidate_count": len(fetch_targets),
                        "time_budget_seconds": self._fetch_total_timeout_seconds(question),
                        "targets": fetch_targets,
                    },
                )
                if event:
                    yield event

                if fetch_targets and target_success_count > 0:
                    with trace_span("execute.web_fetch_pages", result_count=len(fetch_targets)):
                        import time
                        from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

                        def _fetch_target(index: int, target: dict[str, Any]):
                            page = fetch_web_page(str(target.get("url") or ""))
                            page = self._annotate_fetch_page(page, target)
                            return index, target, page

                        attempted_pages: list[Any] = []
                        successful_pages: list[Any] = []
                        next_target_index = 0
                        attempted_fetch_count = 0
                        fetch_budget_seconds = self._fetch_total_timeout_seconds(question)
                        fetch_deadline = time.monotonic() + fetch_budget_seconds if fetch_budget_seconds > 0 else None

                        def _remaining_budget() -> float | None:
                            if fetch_deadline is None:
                                return None
                            return max(0.0, fetch_deadline - time.monotonic())

                        def _record_fetch_result(future, target: dict[str, Any]) -> None:
                            nonlocal attempted_fetch_count
                            attempted_fetch_count += 1
                            try:
                                index, _target, page = future.result()
                            except Exception as exc:
                                from ds_course_agent.tools.web_fetch import WebFetchResult

                                page = WebFetchResult(
                                    url=str(target.get("url") or ""),
                                    error=truncate_error(exc),
                                    metadata={
                                        "source_index": target.get("source_index"),
                                        "source_id": target.get("source_index"),
                                        "source_title": target.get("title"),
                                        "source_url": target.get("url"),
                                        "source_domain": target.get("domain"),
                                    },
                                )
                                index = attempted_fetch_count
                            attempted_pages.append(page)

                            # Emit only successfully browsed pages. Individual failures are
                            # deliberately hidden from the user-facing timeline; the final
                            # summary and source metadata still reflect how many pages were
                            # usable.
                            page_payload = self._page_progress_payload(
                                page,
                                index=index,
                                total=attempted_fetch_count,
                                source_title=str(target.get("title") or ""),
                            )
                            if page_payload["ok"]:
                                successful_pages.append(page)
                                event = self._stream_progress_event(
                                    route_state,
                                    "web_fetch_page_done",
                                    self._short_text(
                                        page_payload["title"] or page_payload["domain"] or page_payload["url"],
                                    ),
                                    tool="web_fetch_tool",
                                    details=page_payload,
                                )
                                if event:
                                    yielded_events.append(event)

                        yielded_events: list[TurnEvent] = []
                        executor = ThreadPoolExecutor(max_workers=max_fetch_workers)
                        try:
                            while (
                                next_target_index < len(fetch_targets)
                                and attempted_fetch_count < max_fetch_attempts
                                and len(successful_pages) < target_success_count
                            ):
                                remaining_budget = _remaining_budget()
                                if remaining_budget is not None and remaining_budget <= 0:
                                    break

                                remaining_attempts = max_fetch_attempts - attempted_fetch_count
                                batch_size = min(
                                    max_fetch_workers,
                                    remaining_attempts,
                                    len(fetch_targets) - next_target_index,
                                )
                                if batch_size <= 0:
                                    break

                                batch_targets = fetch_targets[next_target_index : next_target_index + batch_size]
                                next_target_index += batch_size
                                future_map = {
                                    executor.submit(
                                        _fetch_target, next_target_index - batch_size + offset, target
                                    ): target
                                    for offset, target in enumerate(batch_targets, start=1)
                                }
                                pending = set(future_map)
                                timed_out = False
                                while pending:
                                    remaining_budget = _remaining_budget()
                                    if remaining_budget is not None and remaining_budget <= 0:
                                        timed_out = True
                                        break
                                    done, pending = wait(
                                        pending,
                                        timeout=remaining_budget,
                                        return_when=FIRST_COMPLETED,
                                    )
                                    if not done:
                                        timed_out = True
                                        break
                                    for future in done:
                                        _record_fetch_result(future, future_map[future])
                                    while yielded_events:
                                        yield yielded_events.pop(0)
                                    if len(successful_pages) >= target_success_count:
                                        break
                                for future in pending:
                                    future.cancel()
                                if timed_out:
                                    break
                        finally:
                            executor.shutdown(wait=False, cancel_futures=True)

                        fetch_pages = attempted_pages

                fetch_context = compact_fetched_pages(question, fetch_pages) if fetch_pages else ""
                fetched_count = sum(1 for page in fetch_pages if getattr(page, "ok", False))
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
                    fetched_count=fetched_count,
                    attempted_count=attempted_fetch_count,
                )
                event = self._stream_progress_event(
                    route_state,
                    "web_fetch_done",
                    (
                        f"浏览 {fetched_count} 个页面"
                        if fetched_count
                        else "未成功浏览网页正文，使用搜索摘要生成回答"
                        if attempted_fetch_count
                        else "未浏览网页正文"
                    ),
                    tool="web_fetch_tool",
                    details={
                        "attempted_count": attempted_fetch_count,
                        "fetched_count": fetched_count,
                        "pages": [
                            self._page_progress_payload(page, index=index, total=attempted_fetch_count)
                            for index, page in enumerate(fetch_pages, start=1)
                        ],
                    },
                )
                if event:
                    yield event
        except Exception as exc:
            trace_error("execute.web_fetch_pages", exc)
            event = self._stream_progress_event(
                route_state,
                "web_fetch_error",
                "网页正文读取阶段异常，改用搜索摘要生成回答",
                tool="web_fetch_tool",
                details={
                    "attempted_count": attempted_fetch_count,
                    "fetched_count": fetched_count,
                    "error": truncate_error(exc),
                },
            )
            if event:
                yield event

        return WebFetchContext(
            sources=sources,
            evidence_context=evidence_context,
            attempted_fetch_count=attempted_fetch_count,
            fetched_count=fetched_count,
            fetch_pages=fetch_pages,
        )


__all__ = ["WebPageFetchPipeline"]
