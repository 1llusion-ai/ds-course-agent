"""Invariant tests for frozen production retrieval provenance."""

from __future__ import annotations

import hashlib

from ds_course_agent.kb.corpus_audit import CorpusAuditRecord, audit_corpus_records

REVISION = "a" * 64


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _record(
    chunk_id: str = "chunk-1",
    *,
    page_text: str = "支持向量机通过最大化几何间隔寻找分类超平面。",
    start: int = 0,
    end: int | None = None,
) -> CorpusAuditRecord:
    end = len(page_text) if end is None else end
    text = page_text[start:end]
    return CorpusAuditRecord(
        text=text,
        metadata={
            "metadata_schema_version": "retrieval-provenance/1.0",
            "collection_revision": REVISION,
            "source": "book.pdf",
            "source_id": "book",
            "source_page": 129,
            "book_page": 121,
            "source_char_start": start,
            "source_char_end": end,
            "content_sha256": _sha256(text),
            "source_page_sha256": _sha256(page_text),
            "source_page_text": page_text,
            "chunk_id": chunk_id,
            "chunk_type": "semantic",
        },
    )


def test_audit_accepts_hash_bound_production_records() -> None:
    report = audit_corpus_records(
        [_record()],
        expected_document_count=1,
        expected_collection_revision=REVISION,
    )

    assert report.passed
    assert report.semantic_records == 1


def test_audit_rejects_old_metadata_contract() -> None:
    old = CorpusAuditRecord(
        text="旧块",
        metadata={"chunk_type": "semantic", "source": "book.pdf", "source_page": 125, "chunk_id": "old"},
    )

    report = audit_corpus_records([old])

    assert {issue.code for issue in report.issues} == {"missing_provenance_metadata"}


def test_audit_rejects_hash_interval_revision_and_manifest_drift() -> None:
    record = _record()
    metadata = dict(record.metadata)
    metadata.update(
        {
            "collection_revision": "b" * 64,
            "source_char_end": len(metadata["source_page_text"]) + 1,
            "content_sha256": "0" * 64,
            "source_page_sha256": "1" * 64,
        }
    )

    report = audit_corpus_records(
        [CorpusAuditRecord(record.text, metadata)],
        expected_document_count=2,
        expected_collection_revision=REVISION,
    )

    assert {issue.code for issue in report.issues} == {
        "collection_revision_mismatch",
        "content_hash_mismatch",
        "document_count_mismatch",
        "invalid_source_interval",
        "source_page_hash_mismatch",
    }


def test_audit_rejects_duplicate_ids_and_conflicting_page_snapshots() -> None:
    first = _record("duplicate")
    second = _record("duplicate", page_text="另一份冲突页面快照。")

    report = audit_corpus_records([first, second])

    assert {issue.code for issue in report.issues} == {
        "conflicting_source_page_snapshot",
        "duplicate_chunk_id",
    }
