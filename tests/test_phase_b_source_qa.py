"""Tests for deterministic Phase B development-source QA."""

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
from benchmarks.knowledge_state_search.phase_b_source_qa import validate_source_qa, write_source_qa_report

_TASK_IDS = (
    "pb_t01_cv_variance",
    "pb_t05_p_value_meaning",
    "pb_t09_skewed_summary",
)


def _qa_payloads(
    tmp_path: Path,
) -> tuple[
    tuple[dict[str, object], ...],
    tuple[dict[str, object], ...],
    tuple[dict[str, object], ...],
]:
    candidates: list[dict[str, object]] = []
    sources: list[dict[str, object]] = []
    audits: list[dict[str, object]] = []
    source_index = 0
    for task_index, task_id in enumerate(_TASK_IDS, 1):
        for role_index, (role, count) in enumerate(SOURCE_ROLE_QUOTAS.items(), 1):
            for _ in range(count):
                source_index += 1
                source_id = f"pb_t{task_index:02d}_s{source_index:02d}"
                title = f"Source {source_index}"
                url = f"https://source-{source_index}.example.edu/page"
                provider = f"provider-{role_index}.example.edu"
                text = " ".join(f"s{source_index}_word{word_index}" for word_index in range(50))
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
                    captured_at="2026-07-23T14:00:00+08:00",
                    text=text,
                    sha256="",
                )
                source_payload = source.to_dict()
                source_payload["sha256"] = source.compute_sha256()
                sources.append(source_payload)
                raw_path = tmp_path / f"{source_id}.html"
                verification_path = tmp_path / f"{source_id}.txt"
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
    return tuple(candidates), tuple(sources), tuple(audits)


def test_source_qa_validates_complete_dev_capture_and_keeps_methods_blocked(tmp_path: Path):
    candidates, sources, audits = _qa_payloads(tmp_path)

    report = validate_source_qa(
        candidates,
        sources,
        audits,
        prior_source_files=(),
    )

    assert report["status"] == "pass"
    assert report["captured_source_count"] == 36
    assert report["pending_human_verification_count"] == 36
    assert report["exact_duplicate_excerpts"] == []
    assert report["near_duplicate_current_5gram_containment"] == []
    assert report["annotation_started"] is False
    assert report["method_runs_authorized"] is False


def test_source_qa_rejects_collection_metadata_in_clean_source_rows(tmp_path: Path):
    candidates, sources, audits = _qa_payloads(tmp_path)
    changed = list(sources)
    changed[0] = {**changed[0], "candidate_role": "support-primary"}

    with pytest.raises(ValueError, match="clean source fields"):
        validate_source_qa(
            candidates,
            tuple(changed),
            audits,
            prior_source_files=(),
        )


def test_source_qa_rejects_near_duplicate_excerpts(tmp_path: Path):
    candidates, sources, audits = _qa_payloads(tmp_path)
    changed = list(sources)
    duplicate = dict(changed[1])
    duplicate["text"] = changed[0]["text"]
    duplicate["sha256"] = _source_sha256(duplicate)
    changed[1] = duplicate
    Path(audits[1]["verification_text_path"]).write_text(str(duplicate["text"]), encoding="utf-8")
    changed_audits = list(audits)
    changed_audits[1] = {
        **changed_audits[1],
        "verification_text_sha256": _file_sha256(Path(changed_audits[1]["verification_text_path"])),
    }

    with pytest.raises(ValueError, match="duplicate"):
        validate_source_qa(
            candidates,
            tuple(changed),
            tuple(changed_audits),
            prior_source_files=(),
        )


def test_source_qa_writer_accepts_additional_prior_source_pools(tmp_path: Path):
    candidates, sources, audits = _qa_payloads(tmp_path)
    collection = tmp_path / "collection"
    collection.mkdir()
    for name, rows in (
        ("dev_source_catalog.jsonl", candidates),
        ("verbatim_sources_dev.jsonl", sources),
        ("verbatim_capture_audit.jsonl", audits),
    ):
        (collection / name).write_text(
            "\n".join(json.dumps(row) for row in rows) + "\n",
            encoding="utf-8",
        )
    prior = tmp_path / "prior.jsonl"
    prior.write_text(json.dumps(sources[0]) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="prior"):
        write_source_qa_report(collection, prior_source_files=(prior,))


def _source_sha256(payload: dict[str, object]) -> str:
    fields = (
        "source_id",
        "task_id",
        "title",
        "url",
        "provider",
        "captured_at",
        "text",
    )
    return hashlib.sha256("\n".join(str(payload[field]) for field in fields).encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
