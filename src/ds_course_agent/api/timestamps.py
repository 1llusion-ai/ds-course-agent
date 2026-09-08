"""Timestamp parsing and continuation identity at the API boundary."""

from __future__ import annotations

from datetime import datetime, timezone


def parse_timestamp(value: object, fallback: datetime | None = None) -> datetime | None:
    """Read ISO timestamps without failing an entire history on malformed data."""

    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return fallback


def timestamps_match(left: object, right: object) -> bool:
    """Compare UTC milliseconds, interpreting legacy naive values in server local time.

    Existing timestamps came from datetime.now(); browsers normalize them through
    ISO strings at millisecond precision. Missing or corrupt identities never match.
    """

    first, second = parse_timestamp(left), parse_timestamp(right)
    if first is None or second is None:
        return False
    first, second = first.astimezone(timezone.utc), second.astimezone(timezone.utc)
    return first.replace(microsecond=first.microsecond // 1000 * 1000) == second.replace(
        microsecond=second.microsecond // 1000 * 1000
    )
