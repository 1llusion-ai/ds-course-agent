"""Shared HTTP retry policy for research-model requests."""

from __future__ import annotations

MAX_RATE_LIMIT_BACKOFF_SECONDS = 120.0


def is_retryable_status(status_code: int) -> bool:
    """Return whether an HTTP failure may succeed after backoff."""

    return status_code in {408, 429} or status_code >= 500


def retry_delay(
    *,
    status_code: int | None,
    retry_after: str | None,
    attempt: int,
) -> float:
    """Choose a bounded delay, honoring a server-provided Retry-After value."""

    if status_code == 429:
        value = str(retry_after or "").strip()
        if value:
            try:
                return min(max(float(value), 1.0), MAX_RATE_LIMIT_BACKOFF_SECONDS)
            except ValueError:
                pass
        return min(15.0 * (2 ** (attempt - 1)), MAX_RATE_LIMIT_BACKOFF_SECONDS)
    return float(min(2**attempt, 8))
