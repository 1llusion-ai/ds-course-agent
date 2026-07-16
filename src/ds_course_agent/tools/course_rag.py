"""Course-material RAG tool and source formatting helpers."""

from __future__ import annotations

import os
import re
from typing import Optional

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


def _get_absolute_page(doc) -> Optional[int]:
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


@tool
def course_rag_tool(question: str) -> str:
    """课程资料检索与问答工具。用于基于教材内容回答课程相关问题。"""
    from ds_course_agent.rag.query_trace import trace_step, trace_error, trace_span

    trace_step("tool.invoke", tool="course_rag_tool", question=question)
    try:
        service = get_rag_service()
        with trace_span("tool.course_rag.retrieve"):
            result = service.retrieve(question)
        sources = build_sources_from_documents(result.documents)
        _track_retrieval(sources, used=True)

        if not result.has_results:
            trace_step("tool.result", tool="course_rag_tool", status="no_results")
            no_results_message = (
                f"抱歉，在《{config.COURSE_NAME}》课程资料中未找到与你问题直接相关的内容。\n"
                "建议你：\n"
                "1. 换一个更具体的关键词重新提问\n"
                "2. 说明你想问的概念、章节或例子\n"
                "3. 如果是课程外问题，我也可以先帮你判断是否属于本课程范围"
            )
            _warn_large_tool_result("course_rag_tool", no_results_message, status="no_results")
            return no_results_message

        with trace_span("tool.course_rag.answer"):
            answer_result = service.answer_with_context(question, result.formatted_context)
        trace_step("tool.result", tool="course_rag_tool", status="ok")
        _warn_large_tool_result("course_rag_tool", answer_result.answer, status="ok")
        return answer_result.answer
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
    "course_rag_tool",
    "_get_absolute_page",
    "_track_retrieval",
]
