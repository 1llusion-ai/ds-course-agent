"""Tests for the Phase B dev source-discovery shakeout."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from benchmarks.knowledge_state_search.phase_b_source_shakeout import (
    build_dev_source_candidates,
    build_verbatim_capture_queue,
    normalize_url,
    validate_verbatim_source_record,
    write_dev_source_shakeout,
)


def test_dev_source_candidates_are_balanced_and_preview_safe():
    candidates = build_dev_source_candidates()

    assert len(candidates) == 9
    assert {candidate.task_id for candidate in candidates} == {
        "pb_t01_cv_variance",
        "pb_t05_p_value_meaning",
        "pb_t09_skewed_summary",
    }
    assert all(len(candidate.discovery_preview.split()) <= 25 for candidate in candidates)
    assert all(candidate.url.startswith("https://") for candidate in candidates)
    assert len({normalize_url(candidate.url) for candidate in candidates}) == len(candidates)


def test_source_shakeout_rejects_prior_source_reuse(tmp_path: Path, monkeypatch):
    prior = tmp_path / "prior.jsonl"
    prior.write_text(
        json.dumps({"url": "https://example.edu/page/?utm_source=test"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "benchmarks.knowledge_state_search.phase_b_source_shakeout._PRIOR_SOURCE_FILES",
        (prior,),
    )

    candidates = build_dev_source_candidates()
    assert normalize_url("https://example.edu/page") not in {normalize_url(candidate.url) for candidate in candidates}


def test_source_shakeout_report_keeps_verbatim_capture_and_methods_pending(tmp_path: Path):
    report = write_dev_source_shakeout(tmp_path)

    assert report["status"] == "source_discovery_only"
    assert report["candidate_count"] == 9
    assert report["preview_complete_count"] == 9
    assert report["pending_verbatim_capture_count"] == 9
    assert report["verbatim_capture_complete"] is False
    assert report["annotation_started"] is False
    assert report["method_runs_authorized"] is False
    dedup = json.loads((tmp_path / "url_dedup_report.json").read_text(encoding="utf-8"))
    assert dedup["status"] == "pass"
    queue = json.loads((tmp_path / "verbatim_capture_queue.json").read_text(encoding="utf-8"))
    assert queue["status"] == "pending_human_verbatim_capture"
    assert len(queue["candidates"]) == 9


def test_verbatim_capture_queue_rejects_short_preview_as_final_evidence():
    candidate = build_dev_source_candidates()[0]
    queue = build_verbatim_capture_queue((candidate,))[0]
    assert queue["status"] == "pending"

    payload = {
        "source_id": candidate.source_id,
        "task_id": candidate.task_id,
        "title": candidate.title,
        "url": candidate.url,
        "provider": candidate.provider,
        "captured_at": "2026-07-22T19:35:00+08:00",
        "text": candidate.discovery_preview,
        "sha256": hashlib.sha256(b"incorrect").hexdigest(),
    }
    with pytest.raises(ValueError, match="40-160"):
        validate_verbatim_source_record(payload)
