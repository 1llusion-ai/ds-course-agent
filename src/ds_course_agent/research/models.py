"""Typed intermediate results shared by web research stages."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class SearchResultView:
    """Canonical fields consumed from one raw web-search result."""

    url: str = ""
    title: str = ""
    published_at: str = ""


def _first_result_value(result: Any, names: tuple[str, ...]) -> Any:
    if isinstance(result, Mapping):
        for name in names:
            value = result.get(name)
            if value:
                return value
        return ""

    for name in names:
        value = getattr(result, name, None)
        if value:
            return value
    return ""


def _result_text(result: Any, names: tuple[str, ...]) -> str:
    return str(_first_result_value(result, names) or "").strip()


def adapt_search_result(result: Any) -> SearchResultView:
    """Adapt mapping- or object-shaped search results to one typed view."""

    url = _result_text(result, ("url", "link", "href"))
    return SearchResultView(
        url=url,
        title=_result_text(result, ("title", "name")) or url,
        published_at=_result_text(result, ("published_at", "published_date")),
    )


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


__all__ = ["PreparedWebAnswer", "SearchResultView", "WebFetchContext", "adapt_search_result"]
