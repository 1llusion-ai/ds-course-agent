"""Typed intermediate results shared by web research stages."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PreparedWebAnswer:
    """LLM-ready web evidence or a terminal fallback response."""

    question: str = ""
    chat_history: list[Any] = field(default_factory=list)
    turn_context: str = ""
    fallback: str | None = None
    degraded: bool = False


@dataclass(frozen=True)
class WebFetchContext:
    """Evidence and source metadata produced by the page-fetch stage."""

    sources: list[dict[str, Any]]
    evidence_context: str
    attempted_fetch_count: int
    fetched_count: int
    fetch_pages: list[Any] = field(default_factory=list)


__all__ = ["PreparedWebAnswer", "WebFetchContext"]
