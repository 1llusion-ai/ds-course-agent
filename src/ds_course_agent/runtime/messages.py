"""Convert generic history records to model messages without domain imports."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage


def format_chat_history(chat_history: Iterable[Any]) -> list[BaseMessage]:
    """Convert supported history records into LangChain messages."""

    formatted: list[BaseMessage] = []
    for message in chat_history:
        if isinstance(message, BaseMessage):
            formatted.append(message)
            continue
        if not isinstance(message, Mapping):
            continue
        role = message.get("role", "")
        content = message.get("content", "")
        if role == "user":
            formatted.append(HumanMessage(content=content))
        elif role == "assistant":
            formatted.append(AIMessage(content=content))
        elif role == "system":
            formatted.append(SystemMessage(content=content, additional_kwargs=message.get("additional_kwargs", {})))
    return formatted


def build_chat_messages(
    user_input: str,
    chat_history: Iterable[Any] = (),
    *,
    turn_context: str | None = None,
) -> list[BaseMessage]:
    """Build one model call as turn context, prior history, and user input."""

    messages: list[BaseMessage] = []
    if turn_context and turn_context.strip():
        messages.append(SystemMessage(content=turn_context.strip()))
    messages.extend(format_chat_history(chat_history))
    messages.append(HumanMessage(content=user_input))
    return messages
