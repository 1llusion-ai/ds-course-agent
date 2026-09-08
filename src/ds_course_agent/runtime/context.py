"""Context-budget governance shared by query preparation and model calls."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def warn_context_budget(messages: list[Any], *, location: str, **metadata: Any) -> None:
    """Emit best-effort pre-turn context budget telemetry."""

    try:
        from ds_course_agent.shared.context_governor import warn_if_context_over_budget

        warn_if_context_over_budget(messages, location=location, **metadata)
    except Exception:
        logger.debug("Context budget warning failed at %s", location, exc_info=True)


def govern_context_budget(messages: list[Any], *, location: str, **metadata: Any) -> list[Any]:
    """Compact an over-budget model message list while preserving fail-open behavior."""

    try:
        from ds_course_agent.shared.context_governor import compact_messages_to_budget, warn_if_context_over_budget

        warn_if_context_over_budget(messages, location=location, **metadata)
        return compact_messages_to_budget(messages, location=location, **metadata)
    except Exception as exc:
        try:
            from ds_course_agent.shared.query_trace import trace_error

            trace_error("context_governor.compaction_failed", exc, location=location, **metadata)
        except Exception:
            pass
        logger.warning("Context budget compaction failed at %s", location, exc_info=True)
        return messages


__all__ = ["govern_context_budget", "warn_context_budget"]
