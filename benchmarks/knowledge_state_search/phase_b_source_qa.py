"""Run deterministic QA over captured Phase B development sources."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from benchmarks.knowledge_state_search.evidence import SnapshotSource
from benchmarks.knowledge_state_search.phase_b_source_capture import (
    CaptureVerificationStatus,
    file_sha256,
)
from benchmarks.knowledge_state_search.phase_b_source_catalog import (
    CatalogCandidate,
    validate_catalog,
)
from benchmarks.knowledge_state_search.phase_b_source_shakeout import (
    _PRIOR_SOURCE_FILES,
    normalize_url,
)

DEFAULT_COLLECTION_DIRECTORY = Path("var/artifacts/knowledge_state_search/phase_b_collection")
_SOURCE_FIELDS = frozenset(
    {
        "source_id",
        "task_id",
        "title",
        "url",
        "provider",
        "captured_at",
        "text",
        "sha256",
    }
)
_NEAR_DUPLICATE_CONTAINMENT = 0.80


@dataclass(frozen=True)
class CaptureAuditEntry:
    """Provenance required to verify one locally captured source excerpt."""

    source_id: str
    capture_locator: str
    raw_capture_path: Path
    raw_capture_sha256: str
    verification_text_path: Path
    verification_text_sha256: str
    verification_status: CaptureVerificationStatus

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CaptureAuditEntry:
        """Build one typed capture-audit entry."""

        return cls(
            source_id=_required_string(payload, "source_id"),
            capture_locator=_required_string(payload, "capture_locator"),
            raw_capture_path=Path(_required_string(payload, "raw_capture_path")),
            raw_capture_sha256=_required_string(payload, "raw_capture_sha256"),
            verification_text_path=Path(_required_string(payload, "verification_text_path")),
            verification_text_sha256=_required_string(payload, "verification_text_sha256"),
            verification_status=CaptureVerificationStatus(_required_string(payload, "verification_status")),
        )


def validate_source_qa(
    candidate_payloads: tuple[dict[str, Any], ...],
    source_payloads: tuple[dict[str, Any], ...],
    audit_payloads: tuple[dict[str, Any], ...],
    *,
    prior_source_files: tuple[Path, ...] = _PRIOR_SOURCE_FILES,
    near_duplicate_containment: float = _NEAR_DUPLICATE_CONTAINMENT,
) -> dict[str, object]:
    """Validate composition, provenance, checksums, and source-pool novelty."""

    candidates = tuple(CatalogCandidate.from_dict(payload) for payload in candidate_payloads)
    catalog_report = validate_catalog(candidates, prior_source_files=prior_source_files)
    sources = _load_clean_sources(source_payloads)
    audits = tuple(CaptureAuditEntry.from_dict(payload) for payload in audit_payloads)

    errors: list[str] = []
    candidate_by_id = _unique_by_source_id(candidates, "catalog", errors)
    source_by_id = _unique_by_source_id(sources, "source", errors)
    audit_by_id = _unique_by_source_id(audits, "audit", errors)
    candidate_ids = set(candidate_by_id)
    source_ids = set(source_by_id)
    audit_ids = set(audit_by_id)
    if source_ids != candidate_ids:
        errors.append(
            "captured source IDs must equal catalog IDs: "
            f"missing={sorted(candidate_ids - source_ids)}, extra={sorted(source_ids - candidate_ids)}"
        )
    if audit_ids != source_ids:
        errors.append(
            "capture audit IDs must equal source IDs: "
            f"missing={sorted(source_ids - audit_ids)}, extra={sorted(audit_ids - source_ids)}"
        )

    for source_id in sorted(source_ids & candidate_ids):
        _validate_catalog_match(candidate_by_id[source_id], source_by_id[source_id], errors)
    for source_id in sorted(source_ids & audit_ids):
        _validate_audit(source_by_id[source_id], audit_by_id[source_id], errors)

    prior_sources = _load_prior_sources(prior_source_files)
    exact_duplicates = _exact_duplicate_pairs(sources)
    near_current = _near_duplicate_pairs(
        sources,
        sources,
        threshold=near_duplicate_containment,
        triangular=True,
    )
    near_prior = _near_duplicate_pairs(
        sources,
        prior_sources,
        threshold=near_duplicate_containment,
        triangular=False,
    )
    if exact_duplicates:
        errors.append(f"exact duplicate excerpts found: {exact_duplicates}")
    if near_current:
        errors.append(f"near-duplicate current excerpts found: {near_current}")
    if near_prior:
        errors.append(f"near-duplicate prior excerpts found: {near_prior}")

    source_urls = [normalize_url(source.url) for source in sources]
    if len(source_urls) != len(set(source_urls)):
        errors.append("captured source URLs must be unique after normalization")
    prior_urls = {normalize_url(source.url) for source in prior_sources}
    reused_prior_urls = sorted(url for url in source_urls if url in prior_urls)
    if reused_prior_urls:
        errors.append(f"captured source URLs reuse prior source pool: {reused_prior_urls}")
    if errors:
        raise ValueError("; ".join(errors))

    pending_human = sum(
        entry.verification_status is CaptureVerificationStatus.AGENT_VERIFIED_PENDING_HUMAN for entry in audits
    )
    word_counts = [len(source.text.split()) for source in sources]
    return {
        "status": "pass",
        "catalog_count": len(candidates),
        "captured_source_count": len(sources),
        "task_counts": catalog_report["task_counts"],
        "role_quotas": catalog_report["role_quotas"],
        "role_quota_pass": True,
        "provider_counts": catalog_report["provider_counts"],
        "url_dedup_pass": True,
        "prior_url_reuse": reused_prior_urls,
        "exact_duplicate_excerpts": exact_duplicates,
        "near_duplicate_current_5gram_containment": near_current,
        "near_duplicate_prior_5gram_containment": near_prior,
        "near_duplicate_threshold": near_duplicate_containment,
        "all_excerpt_word_counts": {
            "min": min(word_counts),
            "max": max(word_counts),
        },
        "checksum_valid_count": len(sources),
        "excerpt_match_valid_count": len(sources),
        "human_verified_count": len(audits) - pending_human,
        "pending_human_verification_count": pending_human,
        "annotation_started": False,
        "method_runs_authorized": False,
        "claim_support_labels": ("not_started; candidate_targets are discovery metadata and are not evidence labels"),
    }


def write_source_qa_report(
    collection_directory: str | Path = DEFAULT_COLLECTION_DIRECTORY,
    *,
    prior_source_files: tuple[Path, ...] = _PRIOR_SOURCE_FILES,
) -> dict[str, object]:
    """Load the captured dev artifacts, validate them, and write the QA report."""

    root = Path(collection_directory)
    report = validate_source_qa(
        tuple(_read_jsonl(root / "dev_source_catalog.jsonl")),
        tuple(_read_jsonl(root / "verbatim_sources_dev.jsonl")),
        tuple(_read_jsonl(root / "verbatim_capture_audit.jsonl")),
        prior_source_files=prior_source_files,
    )
    (root / "source_qa_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def build_parser() -> argparse.ArgumentParser:
    """Build the Phase B source-QA CLI."""

    parser = argparse.ArgumentParser(description="Validate captured Phase B development sources.")
    parser.add_argument("--collection", type=Path, default=DEFAULT_COLLECTION_DIRECTORY)
    return parser


def main() -> int:
    """Run source QA and print its machine-readable report."""

    args = build_parser().parse_args()
    report = write_source_qa_report(args.collection)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _load_clean_sources(payloads: tuple[dict[str, Any], ...]) -> tuple[SnapshotSource, ...]:
    sources: list[SnapshotSource] = []
    for payload in payloads:
        if set(payload) != _SOURCE_FIELDS:
            raise ValueError(
                "final-style source rows must contain exactly the clean source fields: "
                f"{sorted(set(payload) - _SOURCE_FIELDS)}"
            )
        source = SnapshotSource.from_dict(payload)
        if not 40 <= len(source.text.split()) <= 160:
            raise ValueError(f"source excerpt must contain 40-160 words: {source.source_id}")
        sources.append(source)
    return tuple(sources)


def _unique_by_source_id(
    rows: tuple[CatalogCandidate, ...] | tuple[SnapshotSource, ...] | tuple[CaptureAuditEntry, ...],
    label: str,
    errors: list[str],
) -> dict[str, CatalogCandidate | SnapshotSource | CaptureAuditEntry]:
    result: dict[str, CatalogCandidate | SnapshotSource | CaptureAuditEntry] = {}
    for row in rows:
        if row.source_id in result:
            errors.append(f"duplicate {label} source_id: {row.source_id}")
        result[row.source_id] = row
    return result


def _validate_catalog_match(
    candidate: CatalogCandidate,
    source: SnapshotSource,
    errors: list[str],
) -> None:
    if source.task_id != candidate.task_id:
        errors.append(f"task_id differs from catalog: {source.source_id}")
    if source.title != candidate.title:
        errors.append(f"title differs from catalog: {source.source_id}")
    if normalize_url(source.url) != normalize_url(candidate.url):
        errors.append(f"URL differs from catalog: {source.source_id}")
    if source.provider != candidate.provider:
        errors.append(f"provider differs from catalog: {source.source_id}")


def _validate_audit(
    source: SnapshotSource,
    audit: CaptureAuditEntry,
    errors: list[str],
) -> None:
    if not audit.capture_locator.strip():
        errors.append(f"capture locator is empty: {source.source_id}")
    if not audit.raw_capture_path.exists():
        errors.append(f"raw capture is missing: {source.source_id}")
    elif file_sha256(audit.raw_capture_path) != audit.raw_capture_sha256:
        errors.append(f"raw capture checksum mismatch: {source.source_id}")
    if not audit.verification_text_path.exists():
        errors.append(f"verification text is missing: {source.source_id}")
        return
    if file_sha256(audit.verification_text_path) != audit.verification_text_sha256:
        errors.append(f"verification text checksum mismatch: {source.source_id}")
    verification_text = audit.verification_text_path.read_text(encoding="utf-8")
    if _normalize_text(source.text) not in _normalize_text(verification_text):
        errors.append(f"excerpt is absent from verification text: {source.source_id}")


def _load_prior_sources(paths: tuple[Path, ...]) -> tuple[SnapshotSource, ...]:
    sources: list[SnapshotSource] = []
    for path in paths:
        if not path.exists():
            continue
        sources.extend(SnapshotSource.from_dict(payload) for payload in _read_jsonl(path))
    return tuple(sources)


def _exact_duplicate_pairs(sources: tuple[SnapshotSource, ...]) -> list[list[str]]:
    normalized: dict[str, list[str]] = {}
    for source in sources:
        normalized.setdefault(_normalize_tokens(source.text), []).append(source.source_id)
    return [source_ids for source_ids in normalized.values() if len(source_ids) > 1]


def _near_duplicate_pairs(
    left: tuple[SnapshotSource, ...],
    right: tuple[SnapshotSource, ...],
    *,
    threshold: float,
    triangular: bool,
) -> list[dict[str, object]]:
    left_grams = {source.source_id: _five_grams(source.text) for source in left}
    right_grams = {source.source_id: _five_grams(source.text) for source in right}
    matches: list[dict[str, object]] = []
    for left_index, left_source in enumerate(left):
        right_rows = right[left_index + 1 :] if triangular else right
        for right_source in right_rows:
            overlap = _minimum_containment(
                left_grams[left_source.source_id],
                right_grams[right_source.source_id],
            )
            if overlap >= threshold:
                matches.append(
                    {
                        "left": left_source.source_id,
                        "right": right_source.source_id,
                        "min_gram_containment": round(overlap, 3),
                    }
                )
    return matches


def _five_grams(text: str) -> frozenset[tuple[str, ...]]:
    tokens = re.findall(r"\w+", text.lower(), flags=re.UNICODE)
    return frozenset(tuple(tokens[index : index + 5]) for index in range(len(tokens) - 4))


def _minimum_containment(
    left: frozenset[tuple[str, ...]],
    right: frozenset[tuple[str, ...]],
) -> float:
    denominator = min(len(left), len(right))
    if denominator == 0:
        return 0.0
    return len(left & right) / denominator


def _normalize_tokens(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.lower(), flags=re.UNICODE))


def _normalize_text(value: str) -> str:
    return " ".join(value.split())


def _required_string(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
