"""Artifact storage and compaction for large tool/RAG payloads.

Phase 1 only warned when a tool result or RAG prompt was large.  This module is
Phase 2 infrastructure inspired by nanobot's tool-result normalization: when a
large payload is observed, persist an immutable copy under ``var/artifacts`` and
emit a trace reference.  It also provides a conservative history compactor that
can replace *old* large tool/tool-like messages with small placeholders pointing
at those artifacts.  Current-turn tool/RAG content should be protected via the
``preserve_recent`` window.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

import ds_course_agent.shared.config as config
from ds_course_agent.shared.context_governor import (
    ContextBudget,
    estimate_text_tokens,
    message_role,
    warn_if_large_text_payload,
)
from ds_course_agent.shared.messages import normalize_content_text
from ds_course_agent.shared.paths import PROJECT_ROOT

_SAFE_SLUG_RE = re.compile(r"[^A-Za-z0-9_.-]+")
TOOL_RESULT_COMPACTED_MARKER = "tool_result_compacted"
_COMPACTABLE_ROLES = {"tool", "function"}
_COMPACTABLE_PAYLOAD_TYPES = {"tool_result", "rag_result", "retrieval_result", "tool"}


@dataclass(frozen=True)
class ToolResultArtifact:
    """Reference to one stored large text payload."""

    path: str
    metadata_path: str
    uri: str
    sha256: str
    chars: int
    bytes: int
    payload_type: str
    location: str
    created_at: str

    def to_trace_dict(self) -> dict[str, Any]:
        return asdict(self)


def _artifact_root(root: str | Path | None = None) -> Path:
    if root is None:
        root = config.TOOL_RESULT_ARTIFACT_DIR
    root_path = Path(root)
    if not root_path.is_absolute():
        root_path = PROJECT_ROOT / root_path
    return root_path


def _relative_or_absolute(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT.resolve()))
    except ValueError:
        return str(path.resolve())


def _safe_slug(value: str, *, max_len: int = 64) -> str:
    value = _SAFE_SLUG_RE.sub("-", str(value or "payload")).strip(".-_")
    if not value:
        value = "payload"
    return value[:max_len]


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return str(value)


def _atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding=encoding) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def store_text_artifact(
    text: Any,
    *,
    location: str,
    payload_type: str,
    source: str = "",
    metadata: dict[str, Any] | None = None,
    root: str | Path | None = None,
) -> ToolResultArtifact:
    """Persist a text payload plus JSON sidecar metadata and return a reference."""

    normalized = normalize_content_text(text)
    encoded = normalized.encode("utf-8")
    digest = sha256(encoded).hexdigest()
    now = datetime.now(timezone.utc)
    root_path = _artifact_root(root)
    day_dir = root_path / now.strftime("%Y%m%d")
    slug_source = source or location or payload_type
    filename = f"{now.strftime('%H%M%S_%f')}_{_safe_slug(slug_source)}_{digest[:12]}.txt"
    payload_path = day_dir / filename
    metadata_path = payload_path.with_suffix(".json")

    artifact = ToolResultArtifact(
        path=_relative_or_absolute(payload_path),
        metadata_path=_relative_or_absolute(metadata_path),
        uri=f"artifact://tool_results/{now.strftime('%Y%m%d')}/{filename}",
        sha256=digest,
        chars=len(normalized),
        bytes=len(encoded),
        payload_type=payload_type,
        location=location,
        created_at=now.isoformat(),
    )

    sidecar = {
        **artifact.to_trace_dict(),
        "source": source,
        "metadata": _json_safe(metadata or {}),
    }

    _atomic_write_text(payload_path, normalized)
    _atomic_write_text(metadata_path, json.dumps(sidecar, ensure_ascii=False, indent=2, sort_keys=True))
    return artifact


def maybe_store_large_text_payload(
    text: Any,
    *,
    location: str,
    payload_type: str,
    budget: ContextBudget | None = None,
    artifact_enabled: bool | None = None,
    **metadata: Any,
) -> dict[str, Any] | None:
    """Warn on large payloads and, when enabled, store an artifact reference.

    Returns ``None`` when the payload is below the large-message threshold.
    Otherwise returns the warning payload with optional ``artifact`` metadata.
    The input text is never modified.
    """

    warning = warn_if_large_text_payload(
        text,
        location=location,
        payload_type=payload_type,
        budget=budget,
        **metadata,
    )
    if warning is None:
        return None

    if artifact_enabled is None:
        artifact_enabled = bool(config.TOOL_RESULT_ARTIFACTS_ENABLED)
    if not artifact_enabled:
        return warning

    source = str(metadata.get("tool") or metadata.get("source") or payload_type)
    artifact = store_text_artifact(
        text,
        location=location,
        payload_type=payload_type,
        source=source,
        metadata=warning,
    )
    payload = {**warning, "artifact": artifact.to_trace_dict()}

    try:
        from ds_course_agent.rag.query_trace import trace_step

        trace_step(
            "tool_result.artifact",
            status="stored",
            location=location,
            payload_type=payload_type,
            source=source,
            artifact=artifact.to_trace_dict(),
        )
    except Exception:
        # Artifact persistence should never disturb tool execution or tests.
        pass

    return payload


def compact_large_tool_messages(
    messages: Sequence[Any],
    *,
    preserve_recent: int = 2,
    budget: ContextBudget | None = None,
    artifact_enabled: bool | None = None,
    root: str | Path | None = None,
    location: str = "history.tool_result_compaction",
    min_chars: int | None = None,
) -> list[Any]:
    """Return a new message list with old large tool results replaced.

    The function is intentionally conservative:

    * it never mutates caller-owned message objects or dicts;
    * the newest ``preserve_recent`` messages are copied through unchanged, so
      the current turn's freshly produced RAG/tool result can remain inline;
    * only tool/function messages or messages explicitly tagged as tool/RAG
      payloads are considered compactable;
    * each compacted payload is first persisted through :func:`store_text_artifact`.
    """

    message_list = list(messages)
    preserve_recent = max(0, int(preserve_recent))
    preserve_from = max(0, len(message_list) - preserve_recent)

    if artifact_enabled is None:
        artifact_enabled = bool(config.TOOL_RESULT_ARTIFACTS_ENABLED)
    if not artifact_enabled:
        return list(message_list)

    budget = budget or ContextBudget()
    threshold_tokens = max(1, int(budget.large_message_tokens))
    inline_limit = min_chars if min_chars is not None else config.TOOL_RESULT_INLINE_MAX_CHARS
    inline_max_chars = max(1, int(inline_limit))

    compacted: list[Any] = []
    compacted_count = 0
    for index, message in enumerate(message_list):
        if index >= preserve_from or _is_compacted_message(message) or not _is_tool_like_message(message):
            compacted.append(message)
            continue

        text = normalize_content_text(_message_content(message))
        estimated_tokens = estimate_text_tokens(text)
        if len(text) <= inline_max_chars and estimated_tokens <= threshold_tokens:
            compacted.append(message)
            continue

        tool_name = _message_tool_name(message)
        payload_type = _message_payload_type(message)
        artifact = store_text_artifact(
            text,
            location=location,
            payload_type=payload_type,
            source=tool_name,
            metadata={
                "tool": tool_name,
                "message_index": index,
                "message_role": message_role(message),
                "estimated_tokens": estimated_tokens,
                "threshold_tokens": threshold_tokens,
                "chars": len(text),
                "compaction": True,
            },
            root=root,
        )
        placeholder = _build_placeholder(
            tool_name=tool_name,
            artifact=artifact,
            chars=len(text),
            estimated_tokens=estimated_tokens,
        )
        compaction_metadata = {
            TOOL_RESULT_COMPACTED_MARKER: True,
            "tool": tool_name,
            "payload_type": payload_type,
            "artifact": artifact.to_trace_dict(),
            "original_chars": len(text),
            "original_estimated_tokens": estimated_tokens,
        }
        compacted.append(_replace_message_content(message, placeholder, compaction_metadata))
        compacted_count += 1

    if compacted_count:
        _trace_compaction(
            location=location,
            compacted_count=compacted_count,
            preserve_recent=preserve_recent,
        )

    return compacted


def _message_content(message: Any) -> Any:
    if isinstance(message, dict):
        return message.get("content", "")
    return getattr(message, "content", message)


def _message_extra(message: Any) -> dict[str, Any]:
    if isinstance(message, dict):
        extra = message.get("additional_kwargs") or {}
        return dict(extra) if isinstance(extra, dict) else {}
    extra = getattr(message, "additional_kwargs", {}) or {}
    return dict(extra) if isinstance(extra, dict) else {}


def _is_compacted_message(message: Any) -> bool:
    if _message_extra(message).get(TOOL_RESULT_COMPACTED_MARKER):
        return True
    text = normalize_content_text(_message_content(message))
    return "[Prior " in text and " result compacted: artifact://" in text


def _is_tool_like_message(message: Any) -> bool:
    role = message_role(message).lower()
    if role in _COMPACTABLE_ROLES:
        return True
    if isinstance(message, dict):
        dict_role = str(message.get("role") or message.get("type") or "").lower()
        if dict_role in _COMPACTABLE_ROLES:
            return True
    extra = _message_extra(message)
    payload_type = str(extra.get("payload_type") or extra.get("type") or "").lower()
    if payload_type in _COMPACTABLE_PAYLOAD_TYPES:
        return True
    return any(key in extra for key in ("tool", "tool_name", "tool_result", "rag_result"))


def _message_tool_name(message: Any) -> str:
    extra = _message_extra(message)
    for value in (
        getattr(message, "name", None),
        extra.get("tool"),
        extra.get("tool_name"),
        extra.get("name"),
    ):
        if value:
            return str(value)
    if isinstance(message, dict):
        for key in ("name", "tool", "tool_name"):
            if message.get(key):
                return str(message[key])
    return "tool"


def _message_payload_type(message: Any) -> str:
    extra = _message_extra(message)
    payload_type = str(extra.get("payload_type") or "").strip()
    if payload_type:
        return payload_type
    role = message_role(message).lower()
    return "tool_result" if role in _COMPACTABLE_ROLES else "rag_result"


def _build_placeholder(
    *,
    tool_name: str,
    artifact: ToolResultArtifact,
    chars: int,
    estimated_tokens: int,
) -> str:
    return (
        f"[Prior {tool_name} result compacted: {artifact.uri} "
        f"({chars} chars, ~{estimated_tokens} tokens). "
        f"Full text saved at {artifact.path}.]"
    )


def _replace_message_content(message: Any, content: str, metadata: dict[str, Any]) -> Any:
    if isinstance(message, dict):
        updated = dict(message)
        updated["content"] = content
        extra = _message_extra(message)
        extra.update(metadata)
        updated["additional_kwargs"] = extra
        return updated

    try:
        from langchain_core.messages import message_to_dict, messages_from_dict

        payload = message_to_dict(message)
        data = payload.setdefault("data", {})
        data["content"] = content
        extra = dict(data.get("additional_kwargs") or {})
        extra.update(metadata)
        data["additional_kwargs"] = extra
        return messages_from_dict([payload])[0]
    except Exception:
        pass

    if hasattr(message, "model_copy"):
        extra = _message_extra(message)
        extra.update(metadata)
        return message.model_copy(update={"content": content, "additional_kwargs": extra})
    if hasattr(message, "copy"):
        extra = _message_extra(message)
        extra.update(metadata)
        return message.copy(update={"content": content, "additional_kwargs": extra})
    return content


def _trace_compaction(*, location: str, compacted_count: int, preserve_recent: int) -> None:
    try:
        from ds_course_agent.rag.query_trace import trace_step

        trace_step(
            "tool_result.compaction",
            status="compacted",
            location=location,
            compacted_count=compacted_count,
            preserve_recent=preserve_recent,
        )
    except Exception:
        pass


__all__ = [
    "TOOL_RESULT_COMPACTED_MARKER",
    "ToolResultArtifact",
    "compact_large_tool_messages",
    "maybe_store_large_text_payload",
    "store_text_artifact",
]
