"""Shared infrastructure for course-agent tools."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ds_course_agent.rag.rag import RAGService


@dataclass
class RetrievalTrace:
    used_retrieval: bool = False
    sources: list[dict] = field(default_factory=list)


_retrieval_trace: ContextVar[Optional[RetrievalTrace]] = ContextVar(
    "retrieval_trace",
    default=None,
)
_rag_service: Optional["RAGService"] = None


def get_rag_service() -> "RAGService":
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
    "end_retrieval_trace",
    "get_retrieval_trace",
    "get_rag_service",
    "_track_retrieval",
    "_warn_large_tool_result",
]
