"""Shared user-facing error response helpers."""

from __future__ import annotations

from typing import Any

TRUNCATED_ERROR_MAX = 160


def truncate_error(error: Any, max_chars: int = TRUNCATED_ERROR_MAX) -> str:
    """Normalize and bound an exception/error string for UI and traces."""

    text = " ".join(str(error or "").split())
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return text[:max_chars]
    return text[: max_chars - 3].rstrip() + "..."


def build_error_response(title: str, detail: str, *, retryable: bool = True) -> str:
    """Build a consistent Markdown error response."""

    retry_hint = "\n\n💡 请稍后重试，或联系管理员。" if retryable else ""
    return f"⚠️ **{title}**\n\n{detail}{retry_hint}"


__all__ = ["TRUNCATED_ERROR_MAX", "build_error_response", "truncate_error"]
