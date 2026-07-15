"""Context budget observation utilities.

This module is intentionally warning-only in v1.  It estimates prompt/message
size, emits logs and query-trace events when a context budget is exceeded, but
never mutates, truncates, summarizes, or offloads messages.
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass
from typing import Any, Iterable

import ds_course_agent.shared.config as config

logger = logging.getLogger(__name__)

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_EN_WORD_RE = re.compile(r"[A-Za-z]+(?:[-'][A-Za-z]+)?")


@dataclass(frozen=True)
class ContextBudget:
    """Soft warning thresholds for prompt/message context."""

    context_window_tokens: int = config.CONTEXT_WINDOW_TOKENS
    budget_ratio: float = config.CONTEXT_BUDGET_RATIO
    large_message_tokens: int = config.CONTEXT_LARGE_MESSAGE_TOKENS

    @property
    def budget_tokens(self) -> int:
        window = max(1, int(self.context_window_tokens))
        ratio = min(max(float(self.budget_ratio), 0.01), 1.0)
        return max(1, int(window * ratio))


DEFAULT_CONTEXT_BUDGET = ContextBudget()


def normalize_content_text(content: Any) -> str:
    """Convert LangChain message content into plain text for estimation."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                value = item.get("text") or item.get("content") or item.get("value")
                if value is not None:
                    parts.append(str(value))
            elif item is not None:
                parts.append(str(item))
        return "\n".join(parts)
    if isinstance(content, dict):
        value = content.get("text") or content.get("content") or content.get("value")
        if value is not None:
            return str(value)
        try:
            return json.dumps(content, ensure_ascii=False, sort_keys=True)
        except TypeError:
            return str(content)
    return str(content)


def estimate_text_tokens(text: Any) -> int:
    """Estimate token count using the agreed lightweight heuristic.

    Chinese/CJK characters are counted as ``chars / 1.5`` and English words as
    ``words / 0.75``.  Remaining non-space characters are counted lightly so
    numbers, operators, and code punctuation still contribute to the estimate.
    """
    value = normalize_content_text(text)
    if not value:
        return 0

    cjk_chars = len(_CJK_RE.findall(value))
    english_words = len(_EN_WORD_RE.findall(value))
    residual = _CJK_RE.sub("", value)
    residual = _EN_WORD_RE.sub("", residual)
    other_chars = len(re.sub(r"\s+", "", residual))

    estimate = (cjk_chars / 1.5) + (english_words / 0.75) + (other_chars / 4.0)
    return int(math.ceil(estimate))


def message_role(message: Any) -> str:
    """Return a stable role/type label for trace/log output."""
    role = getattr(message, "type", None)
    if role:
        return str(role)
    cls_name = type(message).__name__
    if cls_name:
        return cls_name
    if isinstance(message, dict):
        return str(message.get("role") or "dict")
    return "unknown"


def message_content(message: Any) -> Any:
    if isinstance(message, dict):
        return message.get("content", "")
    return getattr(message, "content", message)


def estimate_message_tokens(message: Any) -> int:
    return estimate_text_tokens(message_content(message))


def estimate_messages_tokens(messages: Iterable[Any]) -> int:
    return sum(estimate_message_tokens(message) for message in messages)


def _trace_warning(kind: str, **data: Any) -> None:
    try:
        from ds_course_agent.rag.query_trace import trace_step

        trace_step("context_governor.warning", status="warning", kind=kind, **data)
    except Exception:
        logger.debug("Failed to emit context governor trace", exc_info=True)


def warn_if_context_over_budget(
    messages: Iterable[Any],
    *,
    location: str,
    budget: ContextBudget | None = None,
    **metadata: Any,
) -> dict[str, Any] | None:
    """Warn when a message list exceeds the configured soft context budget.

    Returns a warning payload when over budget, otherwise ``None``.
    """
    budget = budget or DEFAULT_CONTEXT_BUDGET
    message_list = list(messages)
    estimated_tokens = estimate_messages_tokens(message_list)
    budget_tokens = budget.budget_tokens
    if estimated_tokens <= budget_tokens:
        return None

    payload = {
        "location": location,
        "estimated_tokens": estimated_tokens,
        "budget_tokens": budget_tokens,
        "context_window_tokens": budget.context_window_tokens,
        "budget_ratio": budget.budget_ratio,
        "message_count": len(message_list),
        **metadata,
    }
    logger.warning(
        "Context budget warning at %s: estimated_tokens=%s budget_tokens=%s message_count=%s",
        location,
        estimated_tokens,
        budget_tokens,
        len(message_list),
    )
    _trace_warning("context_over_budget", **payload)
    return payload


def warn_if_large_message(
    message: Any,
    *,
    location: str,
    budget: ContextBudget | None = None,
    **metadata: Any,
) -> dict[str, Any] | None:
    """Warn when one message is large enough to threaten later turns."""
    budget = budget or DEFAULT_CONTEXT_BUDGET
    estimated_tokens = estimate_message_tokens(message)
    threshold = max(1, int(budget.large_message_tokens))
    if estimated_tokens <= threshold:
        return None

    payload = {
        "location": location,
        "estimated_tokens": estimated_tokens,
        "threshold_tokens": threshold,
        "message_role": message_role(message),
        **metadata,
    }
    logger.warning(
        "Large message warning at %s: estimated_tokens=%s threshold_tokens=%s role=%s",
        location,
        estimated_tokens,
        threshold,
        payload["message_role"],
    )
    _trace_warning("large_message", **payload)
    return payload

