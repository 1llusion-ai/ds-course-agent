from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Sequence

from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    message_to_dict,
    messages_from_dict,
)

import ds_course_agent.shared.config as config


@dataclass(frozen=True)
class MemoryPolicy:
    """Short-term memory policy: one rolling summary + recent message window."""

    max_recent_messages: int = config.SHORT_MEMORY_RECENT_MESSAGES
    summarize_after_messages: int = config.SHORT_MEMORY_SUMMARIZE_AFTER_MESSAGES
    summary_max_chars: int = config.SHORT_MEMORY_SUMMARY_MAX_CHARS


DEFAULT_MEMORY_POLICY = MemoryPolicy()
SUMMARY_MARKER = "short_memory_summary"
SUMMARY_TITLE = "短期记忆摘要"


def get_history(session_id, memory_policy: MemoryPolicy | None = None):
    return FileChatMessageHistory(
        storage_path=config.storage_path,
        session_id=session_id,
        memory_policy=memory_policy,
    )


class FileChatMessageHistory(BaseChatMessageHistory):
    def __init__(self, storage_path, session_id, memory_policy: MemoryPolicy | None = None):
        self.storage_path = storage_path
        self.session_id = session_id
        self.file_path = os.path.join(self.storage_path, self.session_id)
        self.memory_policy = memory_policy or DEFAULT_MEMORY_POLICY

        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)

    @property
    def messages(self) -> list[BaseMessage]:
        try:
            with open(
                self.file_path,
                "r",
                encoding="utf-8",
            ) as f:
                messages_data = json.load(f)
            return messages_from_dict(messages_data)
        except FileNotFoundError:
            return []

    def add_messages(self, messages: Sequence[BaseMessage]) -> None:
        all_messages = list(self.messages)
        all_messages.extend(messages)
        all_messages = self._compact_messages(all_messages)

        new_messages = [message_to_dict(message) for message in all_messages]
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(new_messages, f, ensure_ascii=False)

    def clear(self) -> None:
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump([], f)

    def delete(self) -> bool:
        """删除历史记录文件"""
        try:
            if os.path.exists(self.file_path):
                os.remove(self.file_path)
                return True
            return False
        except Exception:
            return False

    def _compact_messages(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        policy = self.memory_policy
        max_recent = max(0, int(policy.max_recent_messages))
        summarize_after = max(max_recent + 1, int(policy.summarize_after_messages))

        if len(messages) <= summarize_after:
            return messages

        summary, non_summary = self._split_summary(messages)
        if len(non_summary) <= max_recent:
            return ([summary] if summary else []) + non_summary

        to_summarize = non_summary[:-max_recent] if max_recent else non_summary
        recent = non_summary[-max_recent:] if max_recent else []
        updated_summary = self._build_summary_message(
            previous_summary=self._summary_body(summary) if summary else "",
            messages=to_summarize,
            max_chars=policy.summary_max_chars,
        )
        return [updated_summary] + recent

    def _split_summary(self, messages: list[BaseMessage]) -> tuple[SystemMessage | None, list[BaseMessage]]:
        summary = None
        regular: list[BaseMessage] = []
        for message in messages:
            if self._is_summary_message(message):
                summary = self._merge_summary_messages(summary, message)
            else:
                regular.append(message)
        return summary, regular

    def _merge_summary_messages(
        self,
        current: SystemMessage | None,
        incoming: BaseMessage,
    ) -> SystemMessage:
        if current is None:
            return SystemMessage(
                content=str(getattr(incoming, "content", "")),
                additional_kwargs={SUMMARY_MARKER: True},
            )

        merged_body = "\n".join(
            part for part in [self._summary_body(current), self._summary_body(incoming)] if part
        )
        return self._new_summary_message(self._truncate_text(merged_body, self.memory_policy.summary_max_chars))

    def _is_summary_message(self, message: BaseMessage) -> bool:
        return isinstance(message, SystemMessage) and bool(
            getattr(message, "additional_kwargs", {}).get(SUMMARY_MARKER)
        )

    def _build_summary_message(
        self,
        previous_summary: str,
        messages: list[BaseMessage],
        max_chars: int,
    ) -> SystemMessage:
        parts = []
        if previous_summary:
            parts.append(previous_summary)

        conversation_summary = self._summarize_messages(messages)
        if conversation_summary:
            parts.append(conversation_summary)

        summary = "\n".join(parts).strip()
        summary = self._truncate_text(summary, max_chars)
        return self._new_summary_message(summary)

    def _new_summary_message(self, body: str) -> SystemMessage:
        body = body.strip() or "暂无可用摘要。"
        if body.startswith(f"{SUMMARY_TITLE}：") or body.startswith(f"{SUMMARY_TITLE}:"):
            content = body
        else:
            content = f"{SUMMARY_TITLE}：\n{body}"
        return SystemMessage(content=content, additional_kwargs={SUMMARY_MARKER: True})

    def _summary_body(self, message: BaseMessage) -> str:
        content = str(getattr(message, "content", "") or "").strip()
        content = re.sub(rf"^{SUMMARY_TITLE}[：:]\s*", "", content).strip()
        return content

    def _summarize_messages(self, messages: list[BaseMessage]) -> str:
        """Deterministic extractive summary; no LLM call in persistence path."""
        turns: list[str] = []
        pending_user: str | None = None

        for message in messages:
            content = self._normalize_content(getattr(message, "content", ""))
            if not content:
                continue

            if isinstance(message, HumanMessage) or getattr(message, "type", "") == "human":
                if pending_user:
                    turns.append(f"用户曾问：{pending_user}")
                pending_user = self._truncate_text(content, 120)
                continue

            if isinstance(message, AIMessage) or getattr(message, "type", "") == "ai":
                answer = self._truncate_text(content, 180)
                if pending_user:
                    turns.append(f"用户问：{pending_user}；助手答：{answer}")
                    pending_user = None
                else:
                    turns.append(f"助手曾答：{answer}")

        if pending_user:
            turns.append(f"用户曾问：{pending_user}")

        return "\n".join(f"- {turn}" for turn in turns)

    def _normalize_content(self, content) -> str:
        if isinstance(content, str):
            return re.sub(r"\s+", " ", content).strip()
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    text = item.get("text") or item.get("content")
                    if text:
                        parts.append(str(text))
            return re.sub(r"\s+", " ", " ".join(parts)).strip()
        return re.sub(r"\s+", " ", str(content or "")).strip()

    def _truncate_text(self, text: str, max_chars: int) -> str:
        max_chars = max(1, int(max_chars))
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 1].rstrip() + "…"


def get_all_sessions(storage_path=None):
    """获取所有会话ID列表"""
    if storage_path is None:
        storage_path = config.storage_path

    if not os.path.exists(storage_path):
        return []

    sessions = []
    for filename in os.listdir(storage_path):
        file_path = os.path.join(storage_path, filename)
        if os.path.isfile(file_path):
            sessions.append(filename)
    return sessions


def delete_session(session_id, storage_path=None):
    """删除指定会话的历史记录"""
    if storage_path is None:
        storage_path = config.storage_path

    file_path = os.path.join(storage_path, session_id)
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            return True
        return False
    except Exception:
        return False


def clear_all_sessions(storage_path=None):
    """清空所有会话历史"""
    if storage_path is None:
        storage_path = config.storage_path

    if not os.path.exists(storage_path):
        return 0

    count = 0
    for filename in os.listdir(storage_path):
        file_path = os.path.join(storage_path, filename)
        if os.path.isfile(file_path):
            try:
                os.remove(file_path)
                count += 1
            except Exception:
                pass
    return count
