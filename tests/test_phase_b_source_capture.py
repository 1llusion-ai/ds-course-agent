"""Tests for Phase B natural-source capture validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.knowledge_state_search.phase_b_source_capture import (
    CaptureVerificationStatus,
    VerbatimSourceCapture,
    build_verbatim_source,
    file_sha256,
    write_verbatim_source_capture,
)


def _capture(tmp_path: Path, *, text: str) -> VerbatimSourceCapture:
    raw_path = tmp_path / "page.html"
    verification_path = tmp_path / "page.txt"
    raw_path.write_text(f"<p>{text}</p>", encoding="utf-8")
    verification_path.write_text(text, encoding="utf-8")
    source = build_verbatim_source(
        source_id="pb_t01_s01",
        task_id="pb_t01_cv_variance",
        title="Natural source",
        url="https://example.edu/natural-source",
        provider="example.edu",
        captured_at="2026-07-22T21:30:00+08:00",
        text=text,
    )
    return VerbatimSourceCapture(
        source=source,
        capture_locator="section 1, first paragraph",
        raw_capture_path=str(raw_path),
        raw_capture_sha256=file_sha256(raw_path),
        verification_text_path=str(verification_path),
        verification_text_sha256=file_sha256(verification_path),
        verification_status=CaptureVerificationStatus.AGENT_VERIFIED_PENDING_HUMAN,
    )


def test_verbatim_capture_writes_clean_sources_and_keeps_methods_blocked(tmp_path: Path):
    text = " ".join(f"word{index}" for index in range(50))
    capture = _capture(tmp_path, text=text)

    report = write_verbatim_source_capture((capture,), tmp_path / "output")

    assert report["status"] == "agent_verbatim_capture_complete_pending_human_verification"
    assert report["source_count"] == 1
    assert report["pending_human_verification_count"] == 1
    assert report["annotation_started"] is False
    assert report["method_runs_authorized"] is False
    source_row = json.loads((tmp_path / "output" / "verbatim_sources_dev.jsonl").read_text(encoding="utf-8"))
    assert set(source_row) == {
        "source_id",
        "task_id",
        "title",
        "url",
        "provider",
        "captured_at",
        "text",
        "sha256",
    }
    queue = json.loads((tmp_path / "output" / "verbatim_capture_queue.json").read_text(encoding="utf-8"))
    assert queue["status"] == "agent_captured_pending_human_verification"
    assert queue["pending_verbatim_capture_count"] == 0
    assert queue["pending_human_verification_count"] == 1


def test_verbatim_capture_rejects_excerpt_absent_from_verification_text(tmp_path: Path):
    text = " ".join(f"word{index}" for index in range(50))
    capture = _capture(tmp_path, text=text)
    Path(capture.verification_text_path).write_text(
        " ".join(f"different{index}" for index in range(50)),
        encoding="utf-8",
    )
    changed = VerbatimSourceCapture(
        source=capture.source,
        capture_locator=capture.capture_locator,
        raw_capture_path=capture.raw_capture_path,
        raw_capture_sha256=capture.raw_capture_sha256,
        verification_text_path=capture.verification_text_path,
        verification_text_sha256=file_sha256(capture.verification_text_path),
        verification_status=capture.verification_status,
    )

    with pytest.raises(ValueError, match="excerpt is absent"):
        write_verbatim_source_capture((changed,), tmp_path / "output")
