"""Shared infrastructure for course-agent tools.

This module intentionally keeps small cross-tool helpers in one place:

* HTML/text normalization helpers used by both search snippets and fetched
  pages;
* tool-result tracing helpers.
"""

from __future__ import annotations

import html
import re
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ds_course_agent.shared.config_utils import (
    config_bool,
    config_float,
    config_int,
    config_str,
    config_value,
)

if TYPE_CHECKING:
    from ds_course_agent.rag.rag import RAGService


@dataclass
class RetrievalTrace:
    used_retrieval: bool = False
    sources: list[dict] = field(default_factory=list)


_retrieval_trace: ContextVar[RetrievalTrace | None] = ContextVar(
    "retrieval_trace",
    default=None,
)
_rag_service: RAGService | None = None


def strip_html_tags(text: Any) -> str:
    """Remove scripts/styles/tags and HTML-unescape a small text fragment."""

    value = "" if text is None else str(text)
    value = re.sub(r"<script[\s\S]*?</script>", "", value, flags=re.I)
    value = re.sub(r"<style[\s\S]*?</style>", "", value, flags=re.I)
    value = re.sub(r"<[^>]+>", "", value)
    return html.unescape(value).strip()


def normalize_tool_text(text: Any, *, strip_tags: bool = True) -> str:
    """Normalize external text consistently for tools.

    ``strip_tags=True`` is useful for search snippets and HTML-derived fields.
    Plain text fetchers can pass ``False`` to preserve literal ``<``/``>``
    characters while still normalizing whitespace.
    """

    value = strip_html_tags(text) if strip_tags else ("" if text is None else str(text))
    value = html.unescape(value)
    value = re.sub(r"\r\n?", "\n", value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def truncate_text(text: Any, max_chars: int, *, marker: str = "...") -> tuple[str, bool]:
    """Return ``(text, truncated)`` with a marker when room allows.

    The guard for very small budgets mirrors the safer fetch implementation:
    never return more than ``max_chars`` characters, and avoid appending a marker
    when it would dominate or exceed the requested budget.
    """

    value = str(text or "").strip()
    try:
        limit = int(max_chars)
    except (TypeError, ValueError):
        limit = 0
    if limit <= 0:
        return "", bool(value)
    if len(value) <= limit:
        return value, False
    if limit <= len(marker):
        return value[:limit].rstrip(), True
    return value[: limit - len(marker)].rstrip() + marker, True


def truncate_text_only(text: Any, max_chars: int, *, marker: str = "...") -> str:
    """Return only the truncated string for call sites that do not need a flag."""

    return truncate_text(text, max_chars, marker=marker)[0]


def get_rag_service() -> RAGService:
    global _rag_service
    if _rag_service is None:
        from ds_course_agent.rag.rag import RAGService

        _rag_service = RAGService()
    return _rag_service


def begin_retrieval_trace():
    existing = _retrieval_trace.get()
    if existing is not None:
        return None
    return _retrieval_trace.set(RetrievalTrace())


def end_retrieval_trace(token) -> RetrievalTrace:
    if token is None:
        return _retrieval_trace.get() or RetrievalTrace()
    trace = _retrieval_trace.get() or RetrievalTrace()
    _retrieval_trace.reset(token)
    return trace


def get_retrieval_trace() -> RetrievalTrace:
    return _retrieval_trace.get() or RetrievalTrace()


def _merge_sources(existing: list[dict], incoming: list[dict]) -> list[dict]:
    merged = list(existing)
    seen = set()
    for item in existing:
        if not isinstance(item, dict):
            continue
        key = item.get("url") or item.get("href") or item.get("reference")
        if key:
            seen.add(key)

    for item in incoming:
        if not isinstance(item, dict):
            continue
        reference = item.get("reference")
        key = item.get("url") or item.get("href") or reference
        if not key or key in seen:
            continue
        merged.append(dict(item))
        seen.add(key)

    return merged


def _warn_large_tool_result(tool_name: str, result: str, **metadata) -> None:
    """Apply registry-driven large tool result telemetry/artifact policy."""
    try:
        from ds_course_agent.tools.registry import apply_tool_result_policy

        apply_tool_result_policy(
            tool_name,
            result,
            location=f"tool.{tool_name}.result",
            **metadata,
        )
    except Exception:
        pass


def _track_retrieval(sources: list[dict], used: bool = True) -> None:
    trace = _retrieval_trace.get()
    if trace is None:
        return

    trace.used_retrieval = trace.used_retrieval or used
    trace.sources = _merge_sources(trace.sources, sources)


__all__ = [
    "RetrievalTrace",
    "begin_retrieval_trace",
    "config_bool",
    "config_float",
    "config_int",
    "config_str",
    "config_value",
    "end_retrieval_trace",
    "get_retrieval_trace",
    "get_rag_service",
    "normalize_tool_text",
    "strip_html_tags",
    "truncate_text",
    "truncate_text_only",
    "_track_retrieval",
    "_warn_large_tool_result",
]
