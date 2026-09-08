"""Context budget observation and compaction utilities.

The first version of ContextGovernor was warning-only. Phase 3 keeps those
warnings, but adds a conservative pre-LLM compaction path: when the estimated
message list exceeds the configured budget, older messages are replaced by a
marked ``SystemMessage`` summary while the most recent turn(s) stay verbatim.
"""

from __future__ import annotations

import concurrent.futures
import logging
import math
import re
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

import ds_course_agent.shared.config as config
from ds_course_agent.shared.config_utils import config_bool, config_float, config_int
from ds_course_agent.shared.messages import (
    normalize_content_text,
    raw_message_content,
)

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
CONTEXT_SUMMARY_MARKER = "context_governor_summary"
CONTEXT_SUMMARY_TITLE = "上下文摘要"
_SEMANTIC_SUMMARY_LOCK = threading.Lock()
_SEMANTIC_SUMMARY_IN_FLIGHT: concurrent.futures.Future[str] | None = None
_SEMANTIC_SUMMARY_RETRY_AFTER = 0.0


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
    return raw_message_content(message)


def estimate_message_tokens(message: Any) -> int:
    return estimate_text_tokens(message_content(message))


def estimate_messages_tokens(messages: Iterable[Any]) -> int:
    return sum(estimate_message_tokens(message) for message in messages)


def _trace_warning(kind: str, **data: Any) -> None:
    try:
        from ds_course_agent.shared.query_trace import trace_step

        if "status" in data:
            payload_status = data.pop("status")
            data = {**data, "payload_status": payload_status}
        trace_step("context_governor.warning", status="warning", kind=kind, **data)
    except Exception:
        logger.debug("Failed to emit context governor trace", exc_info=True)


def _trace_action(kind: str, status: str = "ok", **data: Any) -> None:
    try:
        from ds_course_agent.shared.query_trace import trace_step

        trace_step("context_governor.compact", status=status, kind=kind, **data)
    except Exception:
        logger.debug("Failed to emit context governor compaction trace", exc_info=True)


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


def warn_if_large_text_payload(
    text: Any,
    *,
    location: str,
    payload_type: str,
    budget: ContextBudget | None = None,
    **metadata: Any,
) -> dict[str, Any] | None:
    """Warn when a raw text payload, such as a tool result, is large.

    This is also warning-only and returns the original caller-owned text
    untouched.  It exists so tool/RAG boundaries do not need to construct fake
    LangChain messages merely to get size telemetry.
    """
    budget = budget or DEFAULT_CONTEXT_BUDGET
    normalized = normalize_content_text(text)
    estimated_tokens = estimate_text_tokens(normalized)
    threshold = max(1, int(budget.large_message_tokens))
    if estimated_tokens <= threshold:
        return None

    payload = {
        "location": location,
        "payload_type": payload_type,
        "estimated_tokens": estimated_tokens,
        "threshold_tokens": threshold,
        "chars": len(normalized),
        **metadata,
    }
    logger.warning(
        "Large text payload warning at %s: type=%s estimated_tokens=%s threshold_tokens=%s chars=%s",
        location,
        payload_type,
        estimated_tokens,
        threshold,
        len(normalized),
    )
    _trace_warning("large_text_payload", **payload)
    return payload


def is_context_summary_message(message: Any) -> bool:
    """Return whether a message is one of the project's marked summaries."""

    if not isinstance(message, SystemMessage) and message_role(message) != "system":
        return False
    kwargs = getattr(message, "additional_kwargs", {}) or {}
    return bool(kwargs.get(CONTEXT_SUMMARY_MARKER) or kwargs.get("short_memory_summary"))


def _strip_summary_title(text: str) -> str:
    text = str(text or "").strip()
    for title in (CONTEXT_SUMMARY_TITLE, "短期记忆摘要"):
        text = re.sub(rf"^{re.escape(title)}[：:]\s*", "", text).strip()
    return text


def _truncate_text(text: str, max_chars: int) -> str:
    max_chars = max(1, int(max_chars))
    text = str(text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def summarize_message_turns(
    messages: Iterable[Any],
    *,
    max_chars: int | None = None,
    user_max_chars: int = 120,
    assistant_max_chars: int = 180,
    other_max_chars: int = 160,
    include_non_dialogue: bool = False,
    include_context_summaries: bool = False,
) -> str:
    """Deterministically summarize message turns with shared pairing semantics.

    Both persistent short-term memory and transient ContextGovernor compaction use
    this helper so a HumanMessage followed by an AIMessage is summarized as one
    turn everywhere.  Non-dialogue messages remain opt-in: persistence keeps only
    user/assistant turns, while pre-LLM context compaction also records summaries,
    tool outputs, and system context when requested.
    """

    lines: list[str] = []
    pending_user: str | None = None
    for message in messages:
        content = re.sub(r"\s+", " ", normalize_content_text(message_content(message))).strip()
        if not content:
            continue

        if include_context_summaries and is_context_summary_message(message):
            body = _strip_summary_title(content)
            if body:
                lines.append(_truncate_text(body, min(300, max(other_max_chars, 1) * 2)))
            continue

        role = message_role(message)
        if isinstance(message, HumanMessage) or role == "human":
            if pending_user:
                lines.append(f"用户曾问：{pending_user}")
            pending_user = _truncate_text(content, user_max_chars)
            continue

        if isinstance(message, AIMessage) or role == "ai":
            answer = _truncate_text(content, assistant_max_chars)
            if pending_user:
                lines.append(f"用户问：{pending_user}；助手答：{answer}")
                pending_user = None
            else:
                lines.append(f"助手曾答：{answer}")
            continue

        if not include_non_dialogue:
            continue

        if role in {"tool", "ToolMessage"}:
            lines.append(f"工具结果：{_truncate_text(content, other_max_chars)}")
        elif role in {"system", "SystemMessage"}:
            lines.append(f"系统上下文：{_truncate_text(content, other_max_chars)}")
        else:
            lines.append(f"{role}：{_truncate_text(content, other_max_chars)}")

    if pending_user:
        lines.append(f"用户曾问：{pending_user}")

    body = "\n".join(f"- {line}" for line in lines if line).strip()
    if max_chars is None:
        return body
    return _truncate_text(body, max_chars)


def _summarize_messages(messages: Iterable[Any], *, max_chars: int) -> str:
    """Deterministically summarize older context without making an LLM call."""

    return summarize_message_turns(
        messages,
        max_chars=max_chars,
        include_non_dialogue=True,
        include_context_summaries=True,
    )


def _call_summary_model(prompt: str) -> str:
    """Call the configured summary model. Kept separate for monkeypatch tests."""

    from ds_course_agent.shared.llm import get_summary_model

    response = get_summary_model().invoke(prompt)
    content = getattr(response, "content", response)
    return normalize_content_text(content)


def _start_daemon_summary_call(prompt: str) -> concurrent.futures.Future[str]:
    """Run the summary model in one daemon thread and return its Future."""

    future: concurrent.futures.Future[str] = concurrent.futures.Future()

    def _runner() -> None:
        if not future.set_running_or_notify_cancel():
            return
        try:
            future.set_result(_call_summary_model(prompt))
        except BaseException as exc:  # pragma: no cover - defensive bridge to Future
            future.set_exception(exc)

    thread = threading.Thread(
        target=_runner,
        name="context-semantic-summary",
        daemon=True,
    )
    thread.start()
    return future


def _semantic_summarize_source(source: str, *, max_chars: int, timeout_seconds: float) -> str:
    global _SEMANTIC_SUMMARY_IN_FLIGHT, _SEMANTIC_SUMMARY_RETRY_AFTER

    source = str(source or "").strip()
    if not source:
        return ""

    prompt = (
        "请把以下早期对话/工具上下文压缩成中文要点摘要，用于继续辅导学生。"
        "只保留对后续回答有帮助的事实、学生问题、薄弱点和已给出的结论；"
        f"控制在 {max_chars} 个字符以内。\n\n"
        f"{source}"
    )
    timeout_seconds = max(0.1, float(timeout_seconds or 3.0))

    with _SEMANTIC_SUMMARY_LOCK:
        if _SEMANTIC_SUMMARY_IN_FLIGHT is not None:
            if _SEMANTIC_SUMMARY_IN_FLIGHT.done() or _SEMANTIC_SUMMARY_IN_FLIGHT.cancelled():
                _SEMANTIC_SUMMARY_IN_FLIGHT = None
                _SEMANTIC_SUMMARY_RETRY_AFTER = 0.0
            elif _SEMANTIC_SUMMARY_RETRY_AFTER and time.monotonic() >= _SEMANTIC_SUMMARY_RETRY_AFTER:
                # A timed-out daemon thread may still be stuck in provider I/O.
                # Let a later request retry after a short cool-down instead of
                # pinning semantic summaries off forever or spawning a new
                # daemon on every compaction attempt.
                _SEMANTIC_SUMMARY_IN_FLIGHT = None
                _SEMANTIC_SUMMARY_RETRY_AFTER = 0.0
            else:
                raise TimeoutError("previous semantic context summary is still running")
        _SEMANTIC_SUMMARY_IN_FLIGHT = _start_daemon_summary_call(prompt)
        _SEMANTIC_SUMMARY_RETRY_AFTER = 0.0
        future = _SEMANTIC_SUMMARY_IN_FLIGHT

    try:
        summary = future.result(timeout=timeout_seconds)
    except concurrent.futures.TimeoutError as exc:
        # A running Python thread cannot be force-killed safely.  Keep the
        # process-wide guard briefly so repeated compactions do not create an
        # unbounded number of stuck daemon threads, but set a retry-after so the
        # feature can recover without a process restart.
        future.cancel()
        with _SEMANTIC_SUMMARY_LOCK:
            if _SEMANTIC_SUMMARY_IN_FLIGHT is future and not (future.done() or future.cancelled()):
                _SEMANTIC_SUMMARY_RETRY_AFTER = time.monotonic() + max(timeout_seconds, 1.0)
        raise TimeoutError("semantic context summary timed out") from exc
    finally:
        with _SEMANTIC_SUMMARY_LOCK:
            if _SEMANTIC_SUMMARY_IN_FLIGHT is future and (future.done() or future.cancelled()):
                _SEMANTIC_SUMMARY_IN_FLIGHT = None
                _SEMANTIC_SUMMARY_RETRY_AFTER = 0.0

    return _truncate_text(str(summary or "").strip(), max_chars)


def _summarize_messages_for_context(messages: Iterable[Any], *, max_chars: int) -> tuple[str, str]:
    deterministic_source = _summarize_messages(messages, max_chars=max(1000, max_chars * 4)).strip()
    deterministic = _truncate_text(deterministic_source, max_chars).strip()
    if not config_bool("CONTEXT_SEMANTIC_SUMMARY_ENABLED", False):
        return deterministic, "deterministic"

    try:
        semantic = _semantic_summarize_source(
            deterministic_source,
            max_chars=max_chars,
            timeout_seconds=config_float("CONTEXT_SEMANTIC_SUMMARY_TIMEOUT_SECONDS", 3.0, minimum=0.1),
        )
        if semantic:
            _trace_action("semantic_summary", status="ok", summary_chars=len(semantic))
            return semantic, "semantic"
    except Exception as exc:
        try:
            from ds_course_agent.shared.query_trace import trace_error

            trace_error("context_governor.semantic_summary_failed", exc)
        except Exception:
            pass
        logger.warning("Semantic context summary failed; falling back to deterministic summary.", exc_info=True)

    return deterministic, "deterministic_fallback"


def _build_context_summary_message(messages: Iterable[Any], *, max_chars: int) -> SystemMessage:
    body, mode = _summarize_messages_for_context(messages, max_chars=max_chars)
    body = body.strip() or "早期上下文已压缩。"
    return SystemMessage(
        content=f"{CONTEXT_SUMMARY_TITLE}：\n{body}",
        additional_kwargs={CONTEXT_SUMMARY_MARKER: True, "summary_mode": mode},
    )


def compact_messages_to_budget(
    messages: Iterable[BaseMessage],
    *,
    location: str,
    budget: ContextBudget | None = None,
    preserve_recent: int | None = None,
    summary_max_chars: int | None = None,
    **metadata: Any,
) -> list[BaseMessage]:
    """Compact older messages into a marked ``SystemMessage`` when over budget.

    This function is intentionally conservative:
    - leading non-summary system messages (for example the current turn's
      student-profile context) are preserved verbatim;
    - the most recent ``preserve_recent`` messages are preserved verbatim;
    - only the older middle segment is summarized deterministically.
    """

    budget = budget or DEFAULT_CONTEXT_BUDGET
    message_list = list(messages)
    estimated_tokens = estimate_messages_tokens(message_list)
    budget_tokens = budget.budget_tokens
    if estimated_tokens <= budget_tokens:
        return message_list

    preserve_recent = (
        int(preserve_recent)
        if preserve_recent is not None
        else config_int("SHORT_MEMORY_RECENT_MESSAGES", 12, minimum=1)
    )
    preserve_recent = max(1, preserve_recent)
    summary_max_chars = max(
        80,
        int(
            summary_max_chars
            if summary_max_chars is not None
            else config_int("SHORT_MEMORY_SUMMARY_MAX_CHARS", 2000, minimum=1)
        ),
    )

    leading: list[BaseMessage] = []
    index = 0
    while index < len(message_list):
        message = message_list[index]
        if message_role(message) in {"system", "SystemMessage"} and not is_context_summary_message(message):
            leading.append(message)
            index += 1
            continue
        break

    remaining = message_list[index:]
    tail_count = min(len(remaining), preserve_recent)
    if tail_count >= len(remaining) and len(remaining) > 1:
        # Token budget, not message count, is the authority here: even a short
        # history can exceed budget when older messages are very large. Always
        # leave at least one older message available for summarization while
        # preserving the current/latest message verbatim.
        tail_count = 1
    tail = remaining[-tail_count:] if tail_count else []
    to_summarize = remaining[:-tail_count] if tail_count else remaining

    if not to_summarize:
        _trace_action(
            "no_compaction_window",
            status="warning",
            location=location,
            estimated_tokens=estimated_tokens,
            budget_tokens=budget_tokens,
            message_count=len(message_list),
            **metadata,
        )
        return message_list

    summary = _build_context_summary_message(to_summarize, max_chars=summary_max_chars)
    compacted = leading + [summary] + tail
    compacted_tokens = estimate_messages_tokens(compacted)

    if compacted_tokens > budget_tokens and len(summary.content) > 120:
        shrink_ratio = max(0.10, min(0.75, budget_tokens / max(estimated_tokens, 1)))
        smaller_chars = max(80, int(summary_max_chars * shrink_ratio))
        summary = _build_context_summary_message(to_summarize, max_chars=smaller_chars)
        compacted = leading + [summary] + tail
        compacted_tokens = estimate_messages_tokens(compacted)

    if compacted_tokens >= estimated_tokens:
        _trace_action(
            "summary_compaction",
            status="warning",
            location=location,
            estimated_tokens=estimated_tokens,
            compacted_tokens=compacted_tokens,
            budget_tokens=budget_tokens,
            original_message_count=len(message_list),
            compacted_message_count=len(compacted),
            **metadata,
        )
        return message_list

    _trace_action(
        "summary_compaction",
        status="ok" if compacted_tokens <= budget_tokens else "warning",
        location=location,
        estimated_tokens=estimated_tokens,
        compacted_tokens=compacted_tokens,
        budget_tokens=budget_tokens,
        original_message_count=len(message_list),
        compacted_message_count=len(compacted),
        preserved_recent=tail_count,
        **metadata,
    )
    return compacted
