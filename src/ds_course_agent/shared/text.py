"""Low-level text budget helpers shared across domain boundaries."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

TextMarker = str | Callable[[int, int], str]


def truncate_text(
    text: Any,
    max_chars: int,
    *,
    marker: TextMarker = "...",
    strip_whitespace: bool = True,
) -> tuple[str, bool]:
    """Return text within a character budget and whether content was removed.

    ``marker`` may be a fixed string or a factory receiving the source length and
    requested budget.  Callers that need to preserve surrounding whitespace can
    disable the tool-oriented default normalization.
    """

    value = str(text or "")
    if strip_whitespace:
        value = value.strip()

    try:
        limit = int(max_chars)
    except (TypeError, ValueError):
        limit = 0

    if limit <= 0:
        return "", bool(value)
    if len(value) <= limit:
        return value, False

    marker_text = marker(len(value), limit) if callable(marker) else marker
    if limit <= len(marker_text):
        return value[:limit].rstrip(), True
    return value[: limit - len(marker_text)].rstrip() + marker_text, True


__all__ = ["truncate_text"]
