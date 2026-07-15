"""Artifact storage for large tool/RAG payloads.

Phase 1 only warned when a tool result or RAG prompt was large.  This module is
Phase 2 infrastructure inspired by nanobot's tool-result normalization: when a
large payload is observed, persist an immutable copy under ``var/artifacts`` and
emit a trace reference.  The caller-owned text is still returned unchanged in
this slice; replacing old in-flight tool messages with placeholders is a later,
explicit step.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

import ds_course_agent.shared.config as config
from ds_course_agent.shared.context_governor import (
    ContextBudget,
    normalize_content_text,
    warn_if_large_text_payload,
)
from ds_course_agent.shared.paths import PROJECT_ROOT

_SAFE_SLUG_RE = re.compile(r"[^A-Za-z0-9_.-]+")


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


__all__ = [
    "ToolResultArtifact",
    "maybe_store_large_text_payload",
    "store_text_artifact",
]
