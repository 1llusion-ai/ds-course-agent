"""Course-material RAG tool and source formatting helpers."""

from __future__ import annotations

import concurrent.futures
import contextvars
import hashlib
import os
import re
import threading
import time
from collections import OrderedDict

from langchain_core.documents import Document
from langchain_core.tools import tool

import ds_course_agent.shared.config as config
from ds_course_agent.tools._shared import (
    RetrievalTrace,
    _track_retrieval,
    _warn_large_tool_result,
    begin_retrieval_trace,
    end_retrieval_trace,
    get_rag_service,
    get_retrieval_trace,
)


def _get_chapter_start_pages() -> dict[str, int]:
    """Load chapter start pages from the TOC parser when available."""
    try:
        from ds_course_agent.kb.toc_parser import get_toc_parser

        toc = get_toc_parser()
        mapping: dict[str, int] = {}
        for section in toc.sections:
            number = getattr(section, "number", "")
            page = getattr(section, "page", None)
            if not isinstance(number, str) or page is None:
                continue
            if number.startswith("第") and "章" in number:
                mapping[number] = int(page)
        if mapping:
            return mapping
    except Exception:
        pass

    return {
        "第1章": 1,
        "第2章": 15,
        "第3章": 26,
        "第4章": 51,
        "第5章": 77,
        "第6章": 115,
        "第7章": 139,
        "第8章": 160,
        "第9章": 199,
        "第10章": 211,
    }


_CHAPTER_START_PAGES: dict[str, int] = {}
_ANSWER_CACHE_LOCK = threading.RLock()
_ANSWER_CACHE: OrderedDict[str, tuple[float, str]] = OrderedDict()


def _normalize_excerpt_text(text: str, *, max_chars: int = 360) -> str:
    """Return a compact, single-line excerpt safe to show in degraded mode."""

    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(compact) <= max_chars:
        return compact
    return compact[:max_chars].rstrip() + "..."


def _extract_chapter_no(metadata: dict) -> str:
    chapter_no = str(metadata.get("chapter_no") or "").strip()
    if chapter_no:
        return chapter_no

    chapter = str(metadata.get("chapter") or "")
    match = re.search(r"第\s*(\d+)\s*章", chapter)
    if match:
        return f"第{match.group(1)}章"

    source = str(metadata.get("source") or "")
    match = re.search(r"第\s*(\d+)\s*章", source)
    if match:
        return f"第{match.group(1)}章"

    return ""


def _get_absolute_page(doc) -> int | None:
    """Convert chunk-local page information into textbook absolute pages."""
    global _CHAPTER_START_PAGES

    metadata = getattr(doc, "metadata", {}) or {}

    direct_page = metadata.get("book_page")
    if direct_page is not None:
        return int(direct_page)

    direct_page = metadata.get("book_page_start")
    if direct_page is not None:
        return int(direct_page)

    if not _CHAPTER_START_PAGES:
        _CHAPTER_START_PAGES = _get_chapter_start_pages()

    chapter_no = _extract_chapter_no(metadata)
    chapter_start = _CHAPTER_START_PAGES.get(chapter_no)
    if chapter_start is None:
        return None

    relative_page = metadata.get("page")
    if relative_page is None:
        relative_page = metadata.get("page_start")
    if relative_page is None:
        return None

    return chapter_start + int(relative_page) - 1


def _chapter_from_outline_number(metadata: dict) -> tuple[str, str]:
    """Infer the chapter from section/subsection numbers when stored metadata drifts."""
    outline = str(metadata.get("subsection_no") or metadata.get("section_no") or "").strip()
    match = re.match(r"^(\d+)\.", outline)
    if not match:
        return "", ""

    chapter_no = f"第{int(match.group(1))}章"
    try:
        from ds_course_agent.kb.toc_parser import get_toc_parser

        toc = get_toc_parser()
        for section in toc.sections:
            if getattr(section, "level", None) != 1:
                continue
            if str(getattr(section, "number", "")).strip() == chapter_no:
                return chapter_no, str(getattr(section, "name", "") or "").strip()
    except Exception:
        pass

    fallback_names = {
        "第1章": "数据思维",
        "第2章": "数据科学基本知识",
        "第3章": "Python 语言快速入门",
        "第4章": "Python 数据分析",
        "第5章": "数据可视化",
        "第6章": "监督学习常用算法",
        "第7章": "无监督学习算法",
        "第8章": "综合实践",
        "第9章": "大语言模型及其应用",
        "第10章": "数据科学竞赛",
    }
    return chapter_no, fallback_names.get(chapter_no, "")


def _source_chapter_label(metadata: dict) -> tuple[str, str]:
    stored_no = _extract_chapter_no(metadata)
    stored_title = str(metadata.get("chapter") or "").strip()
    inferred_no, inferred_title = _chapter_from_outline_number(metadata)

    if inferred_no and inferred_no != stored_no:
        return inferred_no, inferred_title or stored_title
    if inferred_no and not stored_no:
        return inferred_no, inferred_title or stored_title
    if inferred_no and inferred_no == stored_no and inferred_title:
        return stored_no, inferred_title
    return stored_no, stored_title


def build_sources_from_documents(documents) -> list[dict]:
    sources: list[dict] = []
    seen: set[str] = set()

    for doc in documents or []:
        metadata = getattr(doc, "metadata", {}) or {}
        chapter_no, chapter = _source_chapter_label(metadata)
        abs_page = _get_absolute_page(doc)

        if chapter and chapter_no and abs_page:
            reference = f"《{chapter_no} {chapter}》第{abs_page}页"
        elif chapter and abs_page:
            reference = f"《{chapter}》第{abs_page}页"
        elif chapter and chapter_no:
            reference = f"《{chapter_no} {chapter}》"
        elif chapter:
            reference = f"《{chapter}》"
        else:
            reference = os.path.basename(str(metadata.get("source") or "未知来源"))

        if reference in seen:
            continue
        seen.add(reference)
        sources.append({"reference": reference})

    return sources


def build_extractive_rag_fallback(
    question: str,
    documents: list[Document] | list,
    *,
    error: Exception | str | None = None,
    max_docs: int = 3,
) -> str:
    """Build a grounded fallback answer when the answer LLM is unavailable.

    Retrieval has already succeeded in this branch, so returning a generic
    retry message wastes useful course evidence. This deterministic fallback
    keeps the response grounded by exposing short textbook excerpts and source
    references without pretending that a synthesized LLM answer was produced.
    """

    _ = question  # Reserved for future query-aware extractive scoring.
    usable_docs = [doc for doc in (documents or []) if getattr(doc, "page_content", None)]
    sources = build_sources_from_documents(usable_docs)

    lines = [
        "已检索到课程资料，但生成式回答服务暂时不可用。",
        "先给你可核验的教材片段，便于继续学习：",
        "",
    ]

    if not usable_docs:
        lines.extend(
            [
                f"抱歉，在《{config.COURSE_NAME}》课程资料中暂时无法整理出可展示的片段。",
                "你可以稍后重试，或换一个更具体的关键词重新提问。",
            ]
        )
        return "\n".join(lines)

    for index, doc in enumerate(usable_docs[:max_docs], start=1):
        source = ""
        if index <= len(sources):
            source = sources[index - 1].get("reference") or ""
        excerpt = _normalize_excerpt_text(getattr(doc, "page_content", ""))
        prefix = f"{index}. "
        if source:
            prefix += f"{source}："
        lines.append(f"{prefix}{excerpt}")

    lines.extend(
        [
            "",
            "建议：根据上面的片段先定位关键词；等生成服务恢复后，可以继续追问“请基于这些片段总结/举例”。",
        ]
    )

    if error is not None:
        lines.append("[系统注：本轮已降级为教材片段模式。]")

    return "\n".join(lines)


def build_no_results_message() -> str:
    """Return the standard no-results message for course RAG."""

    return (
        f"抱歉，在《{config.COURSE_NAME}》课程资料中未找到与你问题直接相关的内容。\n"
        "建议你：\n"
        "1. 换一个更具体的关键词重新提问\n"
        "2. 说明你想问的概念、章节或例子\n"
        "3. 如果是课程外问题，我也可以先帮你判断是否属于本课程范围"
    )


def trace_answer_degraded(exc: Exception, *, mode: str) -> None:
    """Record a warning-level RAG answer degradation without failing the turn."""

    from ds_course_agent.rag.query_trace import trace_step

    trace_step(
        "tool.course_rag.answer_degraded",
        status="warning",
        mode=mode,
        error_type=type(exc).__name__,
        error=str(exc)[:200],
    )


def _answer_cache_enabled() -> bool:
    return bool(getattr(config, "RAG_ANSWER_CACHE_ENABLED", True))


def _answer_cache_ttl_seconds() -> float:
    return max(0.0, float(getattr(config, "RAG_ANSWER_CACHE_TTL_SECONDS", 900.0) or 0.0))


def _answer_cache_size() -> int:
    return max(0, int(getattr(config, "RAG_ANSWER_CACHE_SIZE", 128) or 0))


def _rag_answer_timeout_seconds() -> float:
    return max(0.0, float(getattr(config, "RAG_ANSWER_TIMEOUT_SECONDS", 10.0) or 0.0))


def _normalize_answer_cache_question(question: str) -> str:
    return re.sub(r"\s+", "", str(question or "").lower())


def _answer_cache_key(question: str, context: str) -> str:
    context_hash = hashlib.sha256(str(context or "").encode("utf-8")).hexdigest()
    raw = f"{_normalize_answer_cache_question(question)}\n{context_hash}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _trace_answer_cache(stage: str, **data) -> None:
    try:
        from ds_course_agent.rag.query_trace import trace_step

        trace_step(stage, **data)
    except Exception:
        pass


def _get_cached_answer(question: str, context: str) -> str | None:
    maxsize = _answer_cache_size()
    ttl = _answer_cache_ttl_seconds()
    if not _answer_cache_enabled() or maxsize <= 0 or ttl <= 0:
        return None

    key = _answer_cache_key(question, context)
    now = time.monotonic()
    with _ANSWER_CACHE_LOCK:
        cached = _ANSWER_CACHE.get(key)
        if cached is None:
            _trace_answer_cache("rag.answer.cache_miss", reason="not_found", cache_size=len(_ANSWER_CACHE))
            return None
        created_at, answer = cached
        if now - created_at > ttl:
            _ANSWER_CACHE.pop(key, None)
            _trace_answer_cache("rag.answer.cache_miss", reason="expired", cache_size=len(_ANSWER_CACHE))
            return None
        _ANSWER_CACHE.move_to_end(key)
        _trace_answer_cache("rag.answer.cache_hit", cache_size=len(_ANSWER_CACHE), answer_chars=len(answer))
        return answer


def _store_cached_answer(question: str, context: str, answer: str) -> None:
    maxsize = _answer_cache_size()
    ttl = _answer_cache_ttl_seconds()
    if not _answer_cache_enabled() or maxsize <= 0 or ttl <= 0 or not str(answer or "").strip():
        return

    key = _answer_cache_key(question, context)
    with _ANSWER_CACHE_LOCK:
        _ANSWER_CACHE[key] = (time.monotonic(), str(answer))
        _ANSWER_CACHE.move_to_end(key)
        while len(_ANSWER_CACHE) > maxsize:
            _ANSWER_CACHE.popitem(last=False)
    _trace_answer_cache("rag.answer.cache_store", cache_size=len(_ANSWER_CACHE), answer_chars=len(str(answer)))


def clear_rag_answer_cache() -> None:
    """Clear in-process RAG answer cache; useful for tests/benchmarks."""
    with _ANSWER_CACHE_LOCK:
        _ANSWER_CACHE.clear()


def _answer_with_context_timeout_guard(service, question: str, context: str):
    """Invoke answer LLM with a hard per-turn timeout guard."""
    timeout = _rag_answer_timeout_seconds()
    if timeout <= 0:
        return service.answer_with_context(question, context)

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="rag-answer")
    request_context = contextvars.copy_context()
    future = executor.submit(request_context.run, service.answer_with_context, question, context)
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError as exc:
        future.cancel()
        timeout_exc = TimeoutError(f"RAG answer timed out after {timeout:.1f}s")
        _trace_answer_cache("rag.answer.timeout_degraded", status="warning", timeout_seconds=timeout)
        raise timeout_exc from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


@tool
def course_rag_tool(question: str) -> str:
    """课程资料检索与问答工具。用于基于教材内容回答课程相关问题。"""
    from ds_course_agent.rag.query_trace import trace_error, trace_span, trace_step

    trace_step("tool.invoke", tool="course_rag_tool", question=question)
    try:
        service = get_rag_service()
        with trace_span("tool.course_rag.retrieve"):
            result = service.retrieve(question)
        sources = build_sources_from_documents(result.documents)
        _track_retrieval(sources, used=True)

        if not result.has_results:
            trace_step("tool.result", tool="course_rag_tool", status="no_results")
            no_results_message = build_no_results_message()
            _warn_large_tool_result("course_rag_tool", no_results_message, status="no_results")
            return no_results_message

        cached_answer = _get_cached_answer(question, result.formatted_context)
        if cached_answer is not None:
            trace_step("tool.result", tool="course_rag_tool", status="cache_hit")
            _warn_large_tool_result("course_rag_tool", cached_answer, status="cache_hit")
            return cached_answer

        try:
            with trace_span("tool.course_rag.answer"):
                answer_result = _answer_with_context_timeout_guard(
                    service,
                    question,
                    result.formatted_context,
                )
            trace_step("tool.result", tool="course_rag_tool", status="ok")
            _warn_large_tool_result("course_rag_tool", answer_result.answer, status="ok")
            _store_cached_answer(question, result.formatted_context, answer_result.answer)
            return answer_result.answer
        except Exception as answer_exc:
            trace_answer_degraded(answer_exc, mode="sync")
            fallback = build_extractive_rag_fallback(
                question,
                result.documents,
                error=answer_exc,
            )
            trace_step("tool.result", tool="course_rag_tool", status="degraded")
            _warn_large_tool_result("course_rag_tool", fallback, status="degraded")
            return fallback
    except Exception as exc:
        trace_error("tool.invoke", exc, tool="course_rag_tool")
        return f"检索过程中发生错误：{exc}。请稍后重试。"


__all__ = [
    "RetrievalTrace",
    "begin_retrieval_trace",
    "end_retrieval_trace",
    "get_retrieval_trace",
    "get_rag_service",
    "build_sources_from_documents",
    "build_extractive_rag_fallback",
    "build_no_results_message",
    "trace_answer_degraded",
    "clear_rag_answer_cache",
    "course_rag_tool",
    "_get_absolute_page",
    "_track_retrieval",
]
