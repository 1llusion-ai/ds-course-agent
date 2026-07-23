"""Validate Phase B verbatim captures without authorizing annotation or methods."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from benchmarks.knowledge_state_search.evidence import SnapshotSource
from benchmarks.knowledge_state_search.phase_b_source_shakeout import (
    normalize_url,
    validate_verbatim_source_record,
)


class CaptureVerificationStatus(str, Enum):
    """Verification state for one natural-source excerpt."""

    AGENT_VERIFIED_PENDING_HUMAN = "agent_verified_pending_human"
    HUMAN_VERIFIED = "human_verified"


@dataclass(frozen=True)
class VerbatimSourceCapture:
    """One clean source row plus provenance kept outside the final source record."""

    source: SnapshotSource
    capture_locator: str
    raw_capture_path: str
    raw_capture_sha256: str
    verification_text_path: str
    verification_text_sha256: str
    verification_status: CaptureVerificationStatus


def build_verbatim_source(
    *,
    source_id: str,
    task_id: str,
    title: str,
    url: str,
    provider: str,
    captured_at: str,
    text: str,
) -> SnapshotSource:
    """Build a checksum-valid final-style source record."""

    source = SnapshotSource(
        source_id=source_id,
        task_id=task_id,
        title=title,
        url=url,
        provider=provider,
        captured_at=captured_at,
        text=text,
        sha256="",
    )
    payload = source.to_dict()
    payload["sha256"] = source.compute_sha256()
    return validate_verbatim_source_record(payload)


def write_verbatim_source_capture(
    captures: tuple[VerbatimSourceCapture, ...],
    output_directory: str | Path,
) -> dict[str, object]:
    """Write clean source rows, capture provenance, and a human-verification queue."""

    if not captures:
        raise ValueError("at least one verbatim source capture is required")
    _validate_capture_set(captures)

    root = Path(output_directory)
    root.mkdir(parents=True, exist_ok=True)
    source_rows = [capture.source.to_dict() for capture in captures]
    audit_rows = [
        {
            "source_id": capture.source.source_id,
            "capture_locator": capture.capture_locator,
            "raw_capture_path": capture.raw_capture_path,
            "raw_capture_sha256": capture.raw_capture_sha256,
            "verification_text_path": capture.verification_text_path,
            "verification_text_sha256": capture.verification_text_sha256,
            "verification_status": capture.verification_status.value,
        }
        for capture in captures
    ]
    pending = [
        {
            "source_id": capture.source.source_id,
            "task_id": capture.source.task_id,
            "title": capture.source.title,
            "url": capture.source.url,
            "capture_locator": capture.capture_locator,
            "status": "pending_human_page_verification",
        }
        for capture in captures
        if capture.verification_status is not CaptureVerificationStatus.HUMAN_VERIFIED
    ]
    _write_jsonl(root / "verbatim_sources_dev.jsonl", source_rows)
    _write_jsonl(root / "verbatim_capture_audit.jsonl", audit_rows)
    (root / "human_verification_queue.json").write_text(
        json.dumps(
            {
                "status": "complete" if not pending else "pending",
                "pending_count": len(pending),
                "sources": pending,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "verbatim_capture_queue.json").write_text(
        json.dumps(
            {
                "status": "complete" if not pending else "agent_captured_pending_human_verification",
                "required_word_range": [40, 160],
                "captured_count": len(captures),
                "pending_verbatim_capture_count": 0,
                "pending_human_verification_count": len(pending),
                "sources": pending,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    report = {
        "status": (
            "human_verbatim_capture_complete"
            if not pending
            else "agent_verbatim_capture_complete_pending_human_verification"
        ),
        "source_count": len(captures),
        "task_count": len({capture.source.task_id for capture in captures}),
        "word_count_min": min(len(capture.source.text.split()) for capture in captures),
        "word_count_max": max(len(capture.source.text.split()) for capture in captures),
        "checksum_valid_count": len(captures),
        "excerpt_match_valid_count": len(captures),
        "human_verified_count": len(captures) - len(pending),
        "pending_human_verification_count": len(pending),
        "annotation_started": False,
        "method_runs_authorized": False,
    }
    (root / "verbatim_capture_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def file_sha256(path: str | Path) -> str:
    """Return the SHA-256 digest of a local capture file."""

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _validate_capture_set(captures: tuple[VerbatimSourceCapture, ...]) -> None:
    source_ids = [capture.source.source_id for capture in captures]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("verbatim capture source_id values must be unique")
    urls = [normalize_url(capture.source.url) for capture in captures]
    if len(urls) != len(set(urls)):
        raise ValueError("verbatim capture URLs must be unique")
    for capture in captures:
        validate_verbatim_source_record(capture.source.to_dict())
        if not capture.capture_locator.strip():
            raise ValueError(f"capture locator is empty: {capture.source.source_id}")
        raw_path = Path(capture.raw_capture_path)
        verification_path = Path(capture.verification_text_path)
        if file_sha256(raw_path) != capture.raw_capture_sha256:
            raise ValueError(f"raw capture checksum mismatch: {capture.source.source_id}")
        if file_sha256(verification_path) != capture.verification_text_sha256:
            raise ValueError(f"verification text checksum mismatch: {capture.source.source_id}")
        verification_text = verification_path.read_text(encoding="utf-8")
        if _normalize_text(capture.source.text) not in _normalize_text(verification_text):
            raise ValueError(f"excerpt is absent from verification text: {capture.source.source_id}")


def _normalize_text(value: str) -> str:
    return " ".join(value.split())


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows) + "\n",
        encoding="utf-8",
    )
