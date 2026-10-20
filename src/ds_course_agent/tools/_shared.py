"""Shared infrastructure for course-agent tools.

This module intentionally keeps small cross-tool helpers in one place:

* HTML/text normalization helpers used by both search snippets and fetched
  pages;
* tool-result tracing helpers.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ds_course_agent.courses import CourseCatalog, CourseId
from ds_course_agent.courses.resources import DEFAULT_COURSE_ID
from ds_course_agent.shared.config_utils import (
    config_bool,
    config_float,
    config_int,
    config_str,
    config_value,
)
from ds_course_agent.shared.paths import PROJECT_ROOT

if TYPE_CHECKING:
    from ds_course_agent.retrieval.service import RAGService


@dataclass
class RetrievalTrace:
    retrieval_attempted: bool = False
    used_retrieval: bool = False
    sources: list[dict] = field(default_factory=list)


_retrieval_trace: ContextVar[RetrievalTrace | None] = ContextVar(
    "retrieval_trace",
    default=None,
)
_rag_service: RAGService | None = None
_course_rag_services: dict[str, RAGService] = {}
_course_id: ContextVar[str | None] = ContextVar("course_id", default=None)


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


@contextmanager
def course_scope(course_id: str | None) -> Iterator[None]:
    """Bind the current turn's course for tools invoked by the model runtime."""

    token = _course_id.set(str(course_id) if course_id is not None else None)
    try:
        yield
    finally:
        _course_id.reset(token)


def get_current_course_id() -> CourseId:
    """Return the tool call's course identity, using the default only when unbound."""
    return CourseId(_course_id.get() or DEFAULT_COURSE_ID)


def _course_manifest(course_id: str):
    catalog = CourseCatalog.from_directory(PROJECT_ROOT / "data" / "courses")
    manifest = catalog.require(course_id)
    if not manifest.is_ready or manifest.index_binding is None:
        raise RuntimeError(f"course {course_id} does not have a ready retrieval index")
    return manifest


def get_rag_service(course_id: str | None = None) -> RAGService:
    """Return a retrieval service bound to the current course index."""

    global _rag_service
    resolved_course_id = str(course_id or get_current_course_id())
    if resolved_course_id != DEFAULT_COURSE_ID:
        service = _course_rag_services.get(resolved_course_id)
        if service is None:
            from ds_course_agent.retrieval.service import RAGService

            manifest = _course_manifest(resolved_course_id)
            service = RAGService(manifest.index_binding, course_name=manifest.display_name)
            _course_rag_services[resolved_course_id] = service
        return service
    if _rag_service is None:
        from ds_course_agent.retrieval.service import RAGService

        _rag_service = RAGService()
    return _rag_service


def begin_retrieval_trace() -> Token:
    """Start an isolated retrieval scope that will merge into its parent."""

    return _retrieval_trace.set(RetrievalTrace())


def end_retrieval_trace(token: Token) -> RetrievalTrace:
    """Close one retrieval scope and propagate its facts to the parent scope."""

    trace = _retrieval_trace.get() or RetrievalTrace()
    _retrieval_trace.reset(token)
    parent = _retrieval_trace.get()
    if parent is not None:
        parent.retrieval_attempted = parent.retrieval_attempted or trace.retrieval_attempted
        parent.used_retrieval = parent.used_retrieval or trace.used_retrieval
        parent.sources = merge_retrieval_sources(parent.sources, trace.sources)
    return trace


def get_retrieval_trace() -> RetrievalTrace:
    return _retrieval_trace.get() or RetrievalTrace()


def merge_retrieval_sources(existing: list[dict], incoming: list[dict]) -> list[dict]:
    """Merge retrieval sources by their stable reference without duplicates."""

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


def _track_retrieval(
    sources: list[dict],
    *,
    attempted: bool,
    used: bool,
) -> None:
    """Record whether retrieval ran and whether usable evidence was consumed."""

    trace = _retrieval_trace.get()
    if trace is None:
        return

    trace.retrieval_attempted = trace.retrieval_attempted or attempted
    trace.used_retrieval = trace.used_retrieval or used
    trace.sources = merge_retrieval_sources(trace.sources, sources)


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
    "get_current_course_id",
    "get_rag_service",
    "course_scope",
    "merge_retrieval_sources",
    "normalize_tool_text",
    "strip_html_tags",
    "_track_retrieval",
    "_warn_large_tool_result",
]
