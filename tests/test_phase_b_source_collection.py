"""Tests for complete Phase B source-collection QA."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from benchmarks.knowledge_state_search.evidence import SnapshotSource
from benchmarks.knowledge_state_search.phase_b_source_catalog import (
    SOURCE_ROLE_QUOTAS,
    CatalogCandidate,
)
from benchmarks.knowledge_state_search.phase_b_source_collection import (
    validate_source_collection,
    write_source_collection_artifacts,
)


def _collection(tmp_path: Path) -> tuple[tuple[Path, ...], Path]:
    batch_directories: list[Path] = []
    task_rows: list[dict[str, str]] = []
    for batch_index in range(4):
        root = tmp_path / f"batch{batch_index + 1}"
        root.mkdir()
        batch_directories.append(root)
        candidates: list[dict[str, object]] = []
        sources: list[dict[str, object]] = []
        audits: list[dict[str, object]] = []
        access_rows: list[dict[str, object]] = []
        for local_task_index in range(3):
            task_number = batch_index * 3 + local_task_index + 1
            task_id = f"pb_t{task_number:02d}_topic"
            task_rows.append({"task_id": task_id})
            source_number = 0
            for role_index, (role, count) in enumerate(SOURCE_ROLE_QUOTAS.items(), 1):
                for _ in range(count):
                    source_number += 1
                    source_id = f"pb_t{task_number:02d}_s{source_number:02d}"
                    title = f"Source {source_id}"
                    url = f"https://{source_id}.example.edu/page"
                    provider = f"provider-{role_index}.example.edu"
                    text = " ".join(f"{source_id}_word{index}" for index in range(50))
                    candidate = CatalogCandidate(
                        task_id=task_id,
                        source_id=source_id,
                        title=title,
                        url=url,
                        provider=provider,
                        capture_locator="section 1",
                        discovery_query="topic definition",
                        discovery_preview="short discovery preview",
                        candidate_role=role,
                        candidate_targets=(f"{task_id}_c01",),
                    )
                    candidates.append(candidate.to_dict())
                    source = SnapshotSource(
                        source_id=source_id,
                        task_id=task_id,
                        title=title,
                        url=url,
                        provider=provider,
                        captured_at="2026-07-23T18:00:00+08:00",
                        text=text,
                        sha256="",
                    )
                    source_payload = source.to_dict()
                    source_payload["sha256"] = source.compute_sha256()
                    sources.append(source_payload)
                    raw_path = root / f"{source_id}.html"
                    verification_path = root / f"{source_id}.txt"
                    raw_path.write_text(f"<p>{text}</p>", encoding="utf-8")
                    verification_path.write_text(text, encoding="utf-8")
                    audits.append(
                        {
                            "source_id": source_id,
                            "capture_locator": "section 1",
                            "raw_capture_path": str(raw_path),
                            "raw_capture_sha256": _file_sha256(raw_path),
                            "verification_text_path": str(verification_path),
                            "verification_text_sha256": _file_sha256(verification_path),
                            "verification_status": "agent_verified_pending_human",
                        }
                    )
                    access_rows.append(
                        {
                            "source_id": source_id,
                            "http_code": "200",
                            "effective_url": url,
                            "content_type": "text/html",
                            "byte_count": raw_path.stat().st_size,
                            "raw_path": str(raw_path),
                        }
                    )
        _write_jsonl(root / "dev_source_catalog.jsonl", candidates)
        _write_jsonl(root / "verbatim_sources_dev.jsonl", sources)
        _write_jsonl(root / "verbatim_capture_audit.jsonl", audits)
        (root / "url_access_report.json").write_text(
            json.dumps(
                {
                    "status": "pass",
                    "checked_count": len(access_rows),
                    "http_code_counts": {"200": len(access_rows)},
                    "all_directly_accessible": True,
                    "method_runs_authorized": False,
                    "sources": access_rows,
                }
            )
            + "\n",
            encoding="utf-8",
        )
    design_tasks = tmp_path / "tasks.jsonl"
    _write_jsonl(design_tasks, task_rows)
    return tuple(batch_directories), design_tasks


def test_source_collection_validates_144_rows_and_keeps_release_blocked(tmp_path: Path):
    batch_directories, design_tasks = _collection(tmp_path)

    report = validate_source_collection(
        batch_directories,
        design_tasks_file=design_tasks,
        prior_source_files=(),
    )

    assert report["status"] == "pass_pending_human_verification"
    assert report["batch_count"] == 4
    assert report["task_count"] == 12
    assert report["source_count"] == 144
    assert report["source_role_composition_audited"] is True
    assert report["role_quota_pass"] is True
    assert report["role_quotas"] == SOURCE_ROLE_QUOTAS
    assert report["recorded_http_200_count"] == 144
    assert report["pending_human_verification_count"] == 144
    assert report["dataset_frozen"] is False
    assert report["method_runs_authorized"] is False


def test_source_collection_rejects_cross_batch_url_reuse(tmp_path: Path):
    batch_directories, design_tasks = _collection(tmp_path)
    first_source = json.loads(
        (batch_directories[0] / "verbatim_sources_dev.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    second_catalog_path = batch_directories[1] / "dev_source_catalog.jsonl"
    second_catalog = _read_jsonl(second_catalog_path)
    second_catalog[0]["url"] = first_source["url"]
    _write_jsonl(second_catalog_path, second_catalog)

    with pytest.raises(ValueError, match="reuse prior source pool"):
        validate_source_collection(
            batch_directories,
            design_tasks_file=design_tasks,
            prior_source_files=(),
        )


def test_source_collection_writer_emits_clean_rows_and_human_queue(tmp_path: Path):
    batch_directories, design_tasks = _collection(tmp_path)
    output = tmp_path / "output"

    report = write_source_collection_artifacts(
        batch_directories,
        output,
        design_tasks_file=design_tasks,
        prior_source_files=(),
    )

    source_rows = _read_jsonl(output / "agent_captured_sources.jsonl")
    verification_packet = _read_jsonl(output / "human_page_verification_packet.jsonl")
    queue = json.loads((output / "human_verification_queue.json").read_text(encoding="utf-8"))
    assert report["source_count"] == 144
    assert len(source_rows) == 144
    assert report["human_verification_packet_count"] == 144
    assert len(verification_packet) == 144
    assert verification_packet[0]["human_status"] == "pending"
    assert "candidate_role" not in verification_packet[0]
    assert "candidate_targets" not in verification_packet[0]
    assert "candidate_role" not in source_rows[0]
    assert queue["pending_count"] == 144
    assert queue["dataset_frozen"] is False
    assert queue["method_runs_authorized"] is False


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, separators=(",", ":")) for row in rows) + "\n",
        encoding="utf-8",
    )
