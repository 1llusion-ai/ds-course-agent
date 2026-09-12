"""Read-only audit of the frozen production retrieval provenance contract."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

PROVENANCE_SCHEMA_VERSION = "retrieval-provenance/1.0"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_METADATA = (
    "metadata_schema_version",
    "collection_revision",
    "source",
    "source_id",
    "source_page",
    "book_page",
    "source_char_start",
    "source_char_end",
    "content_sha256",
    "source_page_sha256",
    "source_page_text",
    "chunk_id",
    "chunk_type",
)


@dataclass(frozen=True)
class CorpusAuditRecord:
    """One persisted retrieval document presented to the auditor."""

    text: str
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class CorpusAuditIssue:
    """One deterministic production provenance violation."""

    code: str
    source: str
    source_page: int | None
    chunk_id: str
    detail: str


@dataclass(frozen=True)
class CorpusAuditReport:
    """Bounded audit summary suitable for artifacts and release gates."""

    total_records: int
    semantic_records: int
    issues: tuple[CorpusAuditIssue, ...]

    @property
    def passed(self) -> bool:
        """Return True only when every audited contract holds."""

        return not self.issues

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable report."""

        return {
            "passed": self.passed,
            "total_records": self.total_records,
            "semantic_records": self.semantic_records,
            "issue_count": len(self.issues),
            "issues": [asdict(issue) for issue in self.issues],
        }


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_text(value: str) -> str:
    return "".join(value.split())


def _integer(metadata: Mapping[str, Any], key: str) -> int | None:
    value = metadata.get(key)
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _identity(metadata: Mapping[str, Any]) -> tuple[str, int | None, str]:
    return (
        str(metadata.get("source") or ""),
        _integer(metadata, "source_page"),
        str(metadata.get("chunk_id") or ""),
    )


def audit_corpus_records(
    records: Sequence[CorpusAuditRecord],
    *,
    expected_document_count: int | None = None,
    expected_collection_revision: str | None = None,
) -> CorpusAuditReport:
    """Validate collection-wide and per-document production provenance."""

    issues: list[CorpusAuditIssue] = []
    semantic_records = 0
    revisions: set[str] = set()
    chunk_ids: set[str] = set()
    page_snapshots: dict[tuple[str, int], tuple[str, str, int, str, str]] = {}

    if expected_document_count is not None and len(records) != expected_document_count:
        issues.append(
            CorpusAuditIssue(
                "document_count_mismatch",
                "",
                None,
                "",
                f"actual={len(records)}, expected={expected_document_count}",
            )
        )

    for record in records:
        metadata = record.metadata
        source, source_page, chunk_id = _identity(metadata)
        missing = [key for key in _REQUIRED_METADATA if key not in metadata]
        if missing:
            issues.append(
                CorpusAuditIssue("missing_provenance_metadata", source, source_page, chunk_id, ",".join(missing))
            )
            continue

        if metadata.get("chunk_type") != "semantic":
            issues.append(
                CorpusAuditIssue(
                    "unsupported_chunk_type", source, source_page, chunk_id, str(metadata.get("chunk_type"))
                )
            )
            continue
        semantic_records += 1

        if metadata.get("metadata_schema_version") != PROVENANCE_SCHEMA_VERSION:
            issues.append(
                CorpusAuditIssue(
                    "unsupported_provenance_schema",
                    source,
                    source_page,
                    chunk_id,
                    str(metadata.get("metadata_schema_version")),
                )
            )

        revision = str(metadata.get("collection_revision") or "")
        revisions.add(revision)
        if not _SHA256_PATTERN.fullmatch(revision):
            issues.append(CorpusAuditIssue("invalid_collection_revision", source, source_page, chunk_id, revision))
        elif expected_collection_revision is not None and revision != expected_collection_revision:
            issues.append(CorpusAuditIssue("collection_revision_mismatch", source, source_page, chunk_id, revision))

        source_id = str(metadata.get("source_id") or "").strip()
        book_page = _integer(metadata, "book_page")
        start = _integer(metadata, "source_char_start")
        end = _integer(metadata, "source_char_end")
        page_text = metadata.get("source_page_text")
        if (
            not source.strip()
            or not source_id
            or source_page is None
            or source_page < 1
            or book_page is None
            or book_page < 1
        ):
            issues.append(CorpusAuditIssue("invalid_source_identity", source, source_page, chunk_id, source_id))
            continue
        if not chunk_id:
            issues.append(CorpusAuditIssue("invalid_chunk_id", source, source_page, chunk_id, "blank"))
        elif chunk_id in chunk_ids:
            issues.append(CorpusAuditIssue("duplicate_chunk_id", source, source_page, chunk_id, chunk_id))
        chunk_ids.add(chunk_id)

        if not isinstance(page_text, str) or not page_text:
            issues.append(
                CorpusAuditIssue("invalid_source_page_text", source, source_page, chunk_id, "blank or non-string")
            )
            continue
        page_digest = str(metadata.get("source_page_sha256") or "")
        if not _SHA256_PATTERN.fullmatch(page_digest) or _sha256_text(page_text) != page_digest:
            issues.append(CorpusAuditIssue("source_page_hash_mismatch", source, source_page, chunk_id, page_digest))

        if start is None or end is None or start < 0 or end <= start or end > len(page_text):
            issues.append(
                CorpusAuditIssue(
                    "invalid_source_interval",
                    source,
                    source_page,
                    chunk_id,
                    f"start={start}, end={end}, page_length={len(page_text)}",
                )
            )
        else:
            fragment = page_text[start:end]
            if _normalize_text(fragment) != _normalize_text(record.text):
                issues.append(
                    CorpusAuditIssue(
                        "source_interval_content_mismatch", source, source_page, chunk_id, f"start={start}, end={end}"
                    )
                )

        content_digest = str(metadata.get("content_sha256") or "")
        if not _SHA256_PATTERN.fullmatch(content_digest) or _sha256_text(record.text) != content_digest:
            issues.append(CorpusAuditIssue("content_hash_mismatch", source, source_page, chunk_id, content_digest))

        page_key = (source_id, source_page)
        snapshot = (page_digest, page_text, book_page, source, revision)
        previous = page_snapshots.setdefault(page_key, snapshot)
        if previous != snapshot:
            issues.append(
                CorpusAuditIssue("conflicting_source_page_snapshot", source, source_page, chunk_id, source_id)
            )

    if len(revisions) > 1:
        issues.append(CorpusAuditIssue("mixed_collection_revisions", "", None, "", ",".join(sorted(revisions))))

    return CorpusAuditReport(len(records), semantic_records, tuple(issues))


__all__ = ["CorpusAuditIssue", "CorpusAuditRecord", "CorpusAuditReport", "audit_corpus_records"]
