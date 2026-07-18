"""Message/content normalization helpers.

LangChain and provider SDKs can return text as strings, bytes, multimodal
``list[dict]`` blocks, or message objects with ``content``.  Keep those rules
centralized so routing, context governance, and skill executors do not drift.
"""

from __future__ import annotations

import json
import re
from typing import Any


def raw_message_content(message: Any) -> Any:
    """Return the unmodified content payload from a message-like object."""

    if isinstance(message, dict):
        return message.get("content", "")
    return getattr(message, "content", message)


def content_to_text(
    content: Any,
    *,
    list_joiner: str = "\n",
    normalize_whitespace: bool = False,
    dict_keys: tuple[str, ...] = ("text", "content", "value"),
    json_fallback: bool = True,
) -> str:
    """Convert common LLM/LangChain content shapes to text.

    Args:
        content: Message content, stream chunk, or provider response payload.
        list_joiner: Separator used for multimodal/list content.
        normalize_whitespace: Collapse whitespace in the final text.
        dict_keys: Ordered keys to inspect in dict blocks before fallback.
        json_fallback: Serialize unknown dicts as JSON instead of ``str(dict)``.
    """

    if content is None:
        text = ""
    elif isinstance(content, bytes):
        text = content.decode("utf-8", errors="ignore")
    elif isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, (str, bytes)):
                parts.append(
                    content_to_text(
                        item,
                        list_joiner=list_joiner,
                        normalize_whitespace=False,
                        dict_keys=dict_keys,
                        json_fallback=json_fallback,
                    )
                )
            elif isinstance(item, dict):
                value = next((item.get(key) for key in dict_keys if item.get(key) is not None), None)
                if value is not None:
                    parts.append(str(value))
            elif hasattr(item, "text"):
                parts.append(str(item.text))
            elif hasattr(item, "content"):
                parts.append(str(item.content))
            elif item is not None:
                parts.append(str(item))
        text = list_joiner.join(part for part in parts if part)
    elif isinstance(content, dict):
        value = next((content.get(key) for key in dict_keys if content.get(key) is not None), None)
        if value is not None:
            text = str(value)
        elif json_fallback:
            try:
                text = json.dumps(content, ensure_ascii=False, sort_keys=True)
            except TypeError:
                text = str(content)
        else:
            text = str(content)
    else:
        text = str(content)

    if normalize_whitespace:
        return re.sub(r"\s+", " ", text).strip()
    return text


def message_content_text(
    message: Any,
    *,
    list_joiner: str = "\n",
    normalize_whitespace: bool = False,
    dict_keys: tuple[str, ...] = ("text", "content", "value"),
) -> str:
    """Extract a message object's content and convert it to text."""

    return content_to_text(
        raw_message_content(message),
        list_joiner=list_joiner,
        normalize_whitespace=normalize_whitespace,
        dict_keys=dict_keys,
    )


def normalize_content_text(content: Any) -> str:
    """Default plain-text conversion used for token estimation/summaries."""

    return content_to_text(content, list_joiner="\n", normalize_whitespace=False)


def stream_chunk_text(chunk: Any) -> str:
    """Extract streamed delta text while preserving token order."""

    return content_to_text(
        raw_message_content(chunk),
        list_joiner="",
        normalize_whitespace=False,
        dict_keys=("text", "content"),
    )


__all__ = [
    "content_to_text",
    "message_content_text",
    "normalize_content_text",
    "raw_message_content",
    "stream_chunk_text",
]
