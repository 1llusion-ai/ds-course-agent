from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from collections.abc import Sequence
from dataclasses import dataclass

from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import (
    BaseMessage,
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
_SESSION_LOCKS: dict[str, threading.RLock] = {}
_SESSION_LOCKS_GUARD = threading.Lock()


def _get_session_lock(file_path: str) -> threading.RLock:
    """Return one process-local reentrant lock per history file."""
    key = os.path.abspath(file_path)
    with _SESSION_LOCKS_GUARD:
        lock = _SESSION_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _SESSION_LOCKS[key] = lock
        return lock


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
        self._lock = _get_session_lock(self.file_path)

        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)

    @property
    def messages(self) -> list[BaseMessage]:
        with self._lock:
            return self._read_messages_unlocked()

    def _read_messages_unlocked(self) -> list[BaseMessage]:
        try:
            with open(
                self.file_path,
                encoding="utf-8",
            ) as f:
                messages_data = json.load(f)
            return messages_from_dict(messages_data)
        except FileNotFoundError:
            return []

    def add_messages(self, messages: Sequence[BaseMessage]) -> None:
        self._warn_incoming_large_messages(messages)
        with self._lock:
            all_messages = list(self._read_messages_unlocked())
            all_messages.extend(messages)
            all_messages = self._compact_stored_tool_results(
                all_messages,
                preserve_recent=max(1, len(messages)),
            )
            all_messages = self._compact_messages(all_messages)
            self._warn_persisted_context(all_messages)

            new_messages = [message_to_dict(message) for message in all_messages]
            # If this raises, the previous JSON file remains intact because
            # os.replace has not happened yet.  The caller should still treat
            # the current add as not persisted; a Phase 2 checkpoint/JSONL
            # fallback can make user-message persistence recoverable across
            # repeated filesystem failures.
            self._atomic_write_json(new_messages)

    def clear(self) -> None:
        with self._lock:
            self._atomic_write_json([])

    def _atomic_write_json(self, payload) -> None:
        """Atomically replace the history file with a JSON payload."""
        directory = os.path.dirname(self.file_path)
        os.makedirs(directory, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(
            prefix=f".{os.path.basename(self.file_path)}.",
            suffix=".tmp",
            dir=directory,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, self.file_path)
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    def _warn_incoming_large_messages(self, messages: Sequence[BaseMessage]) -> None:
        try:
            from ds_course_agent.shared.context_governor import warn_if_large_message

            for index, message in enumerate(messages):
                warn_if_large_message(
                    message,
                    location="history.add_messages.incoming",
                    session_id=self.session_id,
                    message_index=index,
                )
        except Exception:
            # History persistence must never fail because telemetry failed.
            pass

    def _warn_persisted_context(self, messages: Sequence[BaseMessage]) -> None:
        try:
            from ds_course_agent.shared.context_governor import warn_if_context_over_budget

            warn_if_context_over_budget(
                messages,
                location="history.add_messages.persisted",
                session_id=self.session_id,
                message_count=len(messages),
            )
        except Exception:
            # History persistence must never fail because telemetry failed.
            pass

    def _compact_stored_tool_results(
        self,
        messages: list[BaseMessage],
        *,
        preserve_recent: int,
    ) -> list[BaseMessage]:
        """Offload old large tool messages while preserving newly added ones."""
        try:
            from ds_course_agent.shared.tool_result_store import compact_large_tool_messages

            return compact_large_tool_messages(
                messages,
                preserve_recent=preserve_recent,
                location="history.add_messages.tool_result_compaction",
            )
        except Exception:
            # History persistence must never fail because compaction failed.
            return messages

    def delete(self) -> bool:
        """删除历史记录文件"""
        with self._lock:
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

        merged_body = "\n".join(part for part in [self._summary_body(current), self._summary_body(incoming)] if part)
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
        from ds_course_agent.shared.context_governor import summarize_message_turns

        return summarize_message_turns(
            messages,
            include_non_dialogue=False,
            include_context_summaries=False,
        )

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
