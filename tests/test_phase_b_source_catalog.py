"""Tests for the Phase B dev source-composition catalog."""

from __future__ import annotations

from pathlib import Path

import pytest

from benchmarks.knowledge_state_search.phase_b_source_catalog import (
    SOURCE_ROLE_QUOTAS,
    CatalogCandidate,
    validate_catalog,
    write_catalog,
)

_TASK_IDS = (
    "pb_t01_cv_variance",
    "pb_t05_p_value_meaning",
    "pb_t09_skewed_summary",
)


def _catalog() -> tuple[CatalogCandidate, ...]:
    rows: list[CatalogCandidate] = []
    for task_index, task_id in enumerate(_TASK_IDS, 1):
        for role_index, (role, count) in enumerate(SOURCE_ROLE_QUOTAS.items(), 1):
            for _source_index in range(count):
                rows.append(
                    CatalogCandidate(
                        task_id=task_id,
                        source_id=f"pb_t{task_index:02d}_s{len(rows) + 1:02d}",
                        title=f"Source {len(rows) + 1}",
                        url=f"https://source-{len(rows) + 1}.example.edu/page",
                        provider=f"provider-{role_index}.example.edu",
                        capture_locator="section 1",
                        discovery_query="topic definition",
                        discovery_preview="short discovery preview",
                        candidate_role=role,
                        candidate_targets=(f"{task_id}_c01",),
                    )
                )
    return tuple(rows)


def test_catalog_enforces_36_rows_and_per_task_role_quotas():
    report = validate_catalog(_catalog(), prior_source_files=())

    assert report["status"] == "pass"
    assert report["candidate_count"] == 36
    assert report["task_counts"] == dict.fromkeys(_TASK_IDS, 12)
    assert report["method_runs_authorized"] is False


def test_catalog_rejects_prior_url_reuse(tmp_path: Path):
    prior = tmp_path / "prior.jsonl"
    prior.write_text('{"url":"https://source-1.example.edu/page/"}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="reuse prior source pool"):
        validate_catalog(_catalog(), prior_source_files=(prior,))


def test_catalog_queue_tracks_uncaptured_candidates(tmp_path: Path):
    report = write_catalog(
        _catalog(),
        tmp_path,
        captured_source_ids=frozenset({"pb_t01_s01", "pb_t01_s02"}),
    )

    assert report["captured_count"] == 2
    assert report["pending_verbatim_capture_count"] == 34


def test_catalog_writer_accepts_additional_prior_source_pools(tmp_path: Path):
    prior = tmp_path / "prior.jsonl"
    prior.write_text('{"url":"https://source-1.example.edu/page/"}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="reuse prior source pool"):
        write_catalog(
            _catalog(),
            tmp_path / "output",
            prior_source_files=(prior,),
        )
