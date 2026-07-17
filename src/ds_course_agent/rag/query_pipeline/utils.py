"""Shared query-pipeline text and message helpers."""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Optional

from langchain_core.messages import BaseMessage

import ds_course_agent.shared.config as config
from ds_course_agent.shared.messages import message_content_text

JUDGEMENT_CUES = ["是否", "要不要", "需不需要", "还需要", "还能不能", "可不可以", "有没有必要"]
SUMMARY_MARKER = "short_memory_summary"

SCHEDULE_CUES = [
    "课表", "课程安排", "上课时间", "什么时候上课",
    "几点上课", "上课地点", "在哪上课", "教室",
    "第几周", "周几上课", "第几节",
    "这周有什么课", "本周有什么课", "今天有课吗", "今天有没有课",
    "明天有课吗", "明天有没有课", "后天有课吗", "后天有没有课",
    "今天上课吗", "明天上课吗", "后天上课吗", "下周有什么课",
    "这学期什么时候有课", "本学期什么时候有课",
    "这学期有哪些课", "本学期有哪些课",
    "这学期课程安排", "本学期课程安排",
    "这学期上课安排", "本学期上课安排",
    "下次课", "下一次课", "下节课", "下下节课",
]

DATETIME_CUES = [
    "现在几点",
    "当前时间",
    "现在时间",
    "现在几号",
    "今天几号",
    "今天几月几日",
    "今天星期几",
    "今天周几",
    "今天礼拜几",
    "几号了",
    "星期几",
    "周几",
    "礼拜几",
    "日期",
    "几月几日",
]

FOLLOWUP_CUES = [
    "那它", "那这个", "这个", "那个", "它", "他", "她", "上面", "上述",
    "刚才", "前面", "前面说的", "那为什么", "那怎么", "那是不是",
    "还需要", "那还", "那如果", "这种情况", "继续", "再解释",
    "再讲", "展开", "详细说", "能再解释一下吗", "再解释一下",
    "什么意思", "怎么理解", "需要吗",
]


def _normalize_query_text_uncached(query: str | None) -> str:
    return re.sub(r"\s+", "", (query or "").lower())


@lru_cache(maxsize=max(0, int(config.QUERY_CACHE_SIZE)))
def _normalize_query_text_cached(query: str | None) -> str:
    return _normalize_query_text_uncached(query)


def normalize_query_text(query: str | None) -> str:
    """Normalize user-facing query text for lightweight routing/postprocessing."""
    if not config.QUERY_CACHE_ENABLED:
        return _normalize_query_text_uncached(query)
    if query is None or isinstance(query, str):
        return _normalize_query_text_cached(query)
    # Preserve legacy behavior for unexpected objects rather than forcing them
    # through a cache key conversion.
    return _normalize_query_text_uncached(query)


def clear_query_text_cache() -> None:
    """Clear query text normalization cache; useful for tests/benchmarks."""
    _normalize_query_text_cached.cache_clear()


def query_text_cache_info():
    """Return functools cache_info for normalization cache observability."""
    return _normalize_query_text_cached.cache_info()


def is_judgement_question(query: str | None) -> bool:
    """Return whether the query asks for a yes/no or necessity judgement."""
    normalized = normalize_query_text(query)
    return any(cue in normalized for cue in JUDGEMENT_CUES)


def is_schedule_request(query: str | None) -> bool:
    """Return whether query asks for course schedule / class timing."""
    normalized = normalize_query_text(query)
    if any(cue in normalized for cue in SCHEDULE_CUES):
        return True
    if re.search(r"下{1,}节课", normalized):
        return True
    if re.search(r"第[一二三四五六七八九十百0-9]+[节周]", normalized):
        return True
    if re.search(r"(今天|明天|后天).*(有课|上课|课程安排|几节课)", normalized):
        return True
    if re.search(r"(这学期|本学期|本课程|这门课).*(有课|上课|课程安排|上课安排|课表)", normalized):
        return True
    if re.search(r"什么时候.*(有课|上课)|下.*课.*时间|下次.*上课", normalized):
        return True
    return False


def is_datetime_request(query: str | None) -> bool:
    """Return whether query asks for current date/time, excluding schedule asks."""
    if is_schedule_request(query):
        return False
    normalized = normalize_query_text(query)
    return any(cue in normalized for cue in DATETIME_CUES)


def is_contextual_followup(query: str | None, *, allow_short_question: bool = False) -> bool:
    """Return whether query likely depends on recent conversation context."""
    normalized = normalize_query_text(query)
    if any(cue in normalized for cue in FOLLOWUP_CUES):
        return True
    return bool(allow_short_question and len(normalized) <= 12 and normalized.endswith(("吗", "呢", "？", "?")))


def is_summary_message(message: Any) -> bool:
    """Return whether message is the short-memory summary SystemMessage/dict."""
    if isinstance(message, BaseMessage):
        return getattr(message, "type", "") == "system" and bool(
            getattr(message, "additional_kwargs", {}).get(SUMMARY_MARKER)
        )
    if isinstance(message, dict):
        return message.get("role") == "system" and bool(
            message.get("additional_kwargs", {}).get(SUMMARY_MARKER)
        )
    return False


def message_role(message: Any) -> str:
    """Normalize supported message role shapes to langchain-style role names."""
    if isinstance(message, BaseMessage):
        return getattr(message, "type", "")
    if isinstance(message, dict):
        role = message.get("role", "")
        return {"user": "human", "assistant": "ai", "system": "system"}.get(role, role)
    return ""


def message_content(message: Any) -> str:
    """Extract normalized text from BaseMessage/dict/multimodal messages."""

    return message_content_text(
        message,
        list_joiner=" ",
        normalize_whitespace=True,
        dict_keys=("text", "content"),
    )


def collect_recent_context(
    chat_history: Optional[list[Any]],
    *,
    limit: int = 4,
    include_roles: bool = False,
    ai_truncate_chars: Optional[int] = None,
    include_summary: bool = True,
) -> str:
    """Collect summary-aware recent context from supported chat history shapes."""
    if not chat_history:
        return ""

    summary_messages = [msg for msg in chat_history if is_summary_message(msg)]
    regular_messages = [msg for msg in chat_history if not is_summary_message(msg)]
    parts = []

    if include_summary and summary_messages:
        summary_content = message_content(summary_messages[-1])
        if summary_content:
            parts.append(summary_content)

    for msg in regular_messages[-limit:]:
        content = message_content(msg)
        if not content:
            continue
        role = message_role(msg)
        if role == "ai" and ai_truncate_chars is not None:
            content = content[:ai_truncate_chars]
        if include_roles and role == "human":
            parts.append(f"用户: {content}")
        elif include_roles and role == "ai":
            parts.append(f"助手: {content}")
        else:
            parts.append(content)

    return "\n".join(part for part in parts if part)


def build_grounded_context_query(question: str, recent_context: str) -> str:
    """Build the shared contextual RAG/tool query template."""
    if not recent_context.strip():
        return question
    return (
        "最近对话上下文：\n"
        f"{recent_context}\n\n"
        "请结合上下文理解学生当前追问，再检索课程资料回答。\n"
        f"当前问题：{question}"
    )


def build_grounded_query_from_history(
    question: str,
    chat_history: Optional[list[Any]],
    *,
    allow_short_question: bool = False,
    include_roles: bool = False,
) -> str:
    """Build contextual grounded query directly from chat history when needed."""
    if not is_contextual_followup(question, allow_short_question=allow_short_question):
        return question

    recent_context = collect_recent_context(chat_history, include_roles=include_roles)
    return build_grounded_context_query(question, recent_context)
