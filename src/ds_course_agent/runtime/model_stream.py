"""Decode model and LangGraph streams into user-visible text deltas."""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping
from typing import Any

from langchain_core.messages import AIMessage

from ds_course_agent.shared.messages import message_content_text, stream_chunk_text

logger = logging.getLogger(__name__)

_TEXT_NODES = {"agent", "model"}
_TOOL_NODES = {"tool", "tools"}
_NON_ASSISTANT_TYPES = {"human", "system", "tool"}
_ASSISTANT_TYPES = {"ai", "aimessagechunk"}


def extract_agent_response(result: dict[str, Any]) -> str:
    """Return the latest assistant text from a LangGraph invocation result."""

    messages = result.get("messages", [])
    for message in reversed(messages):
        if isinstance(message, AIMessage) and message.content:
            return message_content_text(message, list_joiner="", dict_keys=("text", "content"))
    return ""


def extract_model_text(message: object) -> str:
    """Normalize a direct model response or chunk to text."""

    return stream_chunk_text(message)


def iter_text_chunks(text: str, chunk_size: int = 24) -> Iterator[str]:
    """Yield deterministic coarse chunks for a recovered buffered response."""

    if not text:
        return
    for index in range(0, len(text), chunk_size):
        yield text[index : index + chunk_size]


def iter_agent_stream_messages(graph_agent: Any, messages: list[Any]) -> Iterator[str]:
    """Yield assistant deltas while filtering tool and non-assistant messages."""

    if graph_agent is None:
        raise RuntimeError("Tool-agent streaming requires an explicit allowlisted graph agent")

    stats: dict[str, object] = {
        "seen": 0,
        "emitted": 0,
        "skipped_empty": 0,
        "skipped_tool": 0,
        "skipped_non_assistant": 0,
        "skipped_node": 0,
        "nodes": {},
    }
    try:
        for item in graph_agent.stream({"messages": messages}, stream_mode="messages"):
            chunk, metadata = _unpack_stream_item(item)
            stats["seen"] = int(stats["seen"]) + 1
            node = _stream_node(metadata)
            if node:
                nodes = stats["nodes"]
                if isinstance(nodes, dict):
                    nodes[node] = int(nodes.get(node, 0)) + 1

            text, skip_reason = _stream_delta_text(chunk, metadata)
            if text:
                stats["emitted"] = int(stats["emitted"]) + 1
                yield text
                continue

            key = f"skipped_{skip_reason}"
            if key in stats:
                stats[key] = int(stats[key]) + 1
    finally:
        _trace_stream_stats(stats)


def _unpack_stream_item(item: object) -> tuple[object, Mapping[str, object]]:
    if isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], Mapping):
        return item[0], item[1]
    return item, {}


def _stream_node(metadata: Mapping[str, object] | None) -> str:
    if not metadata:
        return ""
    return str(metadata.get("langgraph_node") or "")


def _stream_message_type(chunk: object) -> str:
    message_type = getattr(chunk, "type", "")
    if message_type:
        return str(message_type).lower()
    return type(chunk).__name__.lower()


def _stream_delta_text(chunk: object, metadata: Mapping[str, object] | None) -> tuple[str, str]:
    node = _stream_node(metadata)
    message_type = _stream_message_type(chunk)

    if node.lower() in _TOOL_NODES or message_type in {"tool", "toolmessage"}:
        return "", "tool"
    if message_type in _NON_ASSISTANT_TYPES:
        return "", "non_assistant"
    if node and node.lower() not in _TEXT_NODES and message_type not in _ASSISTANT_TYPES:
        return "", "node"

    text = extract_model_text(chunk)
    if not text:
        return "", "empty"
    return text, ""


def _trace_stream_stats(stats: dict[str, object]) -> None:
    try:
        from ds_course_agent.shared.query_trace import trace_step

        trace_step("agent.stream_messages", **stats)
    except Exception:
        logger.debug("Failed to emit agent stream message stats", exc_info=True)


__all__ = [
    "extract_agent_response",
    "extract_model_text",
    "iter_agent_stream_messages",
    "iter_text_chunks",
]
