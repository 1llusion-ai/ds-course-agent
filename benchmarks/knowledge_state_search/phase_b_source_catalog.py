"""Validate one Phase B source-composition batch before capture."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from benchmarks.knowledge_state_search.phase_b_source_shakeout import (
    _PRIOR_SOURCE_FILES,
    normalize_url,
)

SOURCE_ROLE_QUOTAS = {
    "support-primary": 5,
    "partial-primary": 2,
    "contradiction-primary": 1,
    "topical-distractor-primary": 3,
    "unrelated-primary": 1,
}


@dataclass(frozen=True)
class CatalogCandidate:
    """One candidate source in the pre-capture composition catalog."""

    task_id: str
    source_id: str
    title: str
    url: str
    provider: str
    capture_locator: str
    discovery_query: str
    discovery_preview: str
    candidate_role: str
    candidate_targets: tuple[str, ...]
    collection_note: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CatalogCandidate:
        """Build one typed catalog row."""

        targets = payload.get("candidate_targets")
        if not isinstance(targets, list) or not all(isinstance(item, str) for item in targets):
            raise ValueError("candidate_targets must be a list of strings")
        return cls(
            task_id=_required_string(payload, "task_id"),
            source_id=_required_string(payload, "source_id"),
            title=_required_string(payload, "title"),
            url=_required_string(payload, "url"),
            provider=_required_string(payload, "provider"),
            capture_locator=_required_string(payload, "capture_locator"),
            discovery_query=_required_string(payload, "discovery_query"),
            discovery_preview=_required_string(payload, "discovery_preview"),
            candidate_role=_required_string(payload, "candidate_role"),
            candidate_targets=tuple(targets),
            collection_note=str(payload.get("collection_note", "")).strip(),
        )

    def to_dict(self) -> dict[str, object]:
        """Serialize the catalog row without presenting it as final evidence."""

        return {
            "task_id": self.task_id,
            "source_id": self.source_id,
            "title": self.title,
            "url": self.url,
            "provider": self.provider,
            "capture_locator": self.capture_locator,
            "discovery_query": self.discovery_query,
            "discovery_preview": self.discovery_preview,
            "preview_word_count": len(self.discovery_preview.split()),
            "candidate_role": self.candidate_role,
            "candidate_targets": list(self.candidate_targets),
            "collection_note": self.collection_note,
            "capture_status": "pending_verbatim_capture",
            "usable_as_final_evidence": False,
        }


def validate_catalog(
    candidates: tuple[CatalogCandidate, ...],
    *,
    prior_source_files: tuple[Path, ...] = _PRIOR_SOURCE_FILES,
) -> dict[str, object]:
    """Validate exact task counts, role quotas, and URL/source-pool novelty."""

    errors: list[str] = []
    task_ids = tuple(dict.fromkeys(item.task_id for item in candidates))
    if len(task_ids) != 3:
        errors.append(f"catalog batch must contain exactly three tasks: {task_ids}")
    if len(candidates) != len(task_ids) * sum(SOURCE_ROLE_QUOTAS.values()):
        errors.append(f"catalog must contain exactly {len(task_ids) * 12} candidates")
    task_counts = {task_id: sum(item.task_id == task_id for item in candidates) for task_id in task_ids}
    if any(count != 12 for count in task_counts.values()):
        errors.append(f"task counts must each equal 12: {task_counts}")
    for task_id in task_ids:
        role_counts = {
            role: sum(item.task_id == task_id and item.candidate_role == role for item in candidates)
            for role in SOURCE_ROLE_QUOTAS
        }
        if role_counts != SOURCE_ROLE_QUOTAS:
            errors.append(f"role quotas failed for {task_id}: {role_counts}")
        providers = {item.provider for item in candidates if item.task_id == task_id}
        if len(providers) < 5:
            errors.append(f"provider diversity too low for {task_id}: {sorted(providers)}")
        if sum(item.task_id == task_id and "wikipedia.org" in item.provider.lower() for item in candidates) > 1:
            errors.append(f"more than one wiki candidate for {task_id}")
    source_ids = [item.source_id for item in candidates]
    if len(source_ids) != len(set(source_ids)):
        errors.append("source_id values must be unique")
    urls = [normalize_url(item.url) for item in candidates]
    if len(urls) != len(set(urls)):
        errors.append("candidate URLs must be unique after normalization")
    prior_urls = _load_prior_urls(prior_source_files)
    reused_urls = sorted(url for url in urls if url in prior_urls)
    if reused_urls:
        errors.append(f"candidate URLs reuse prior source pool: {reused_urls}")
    if any(len(item.discovery_preview.split()) > 25 for item in candidates):
        errors.append("discovery previews must contain at most 25 words")
    if any(item.candidate_role not in SOURCE_ROLE_QUOTAS for item in candidates):
        errors.append("candidate_role contains an unsupported composition role")
    if errors:
        raise ValueError("; ".join(errors))
    return {
        "status": "pass",
        "candidate_count": len(candidates),
        "task_counts": task_counts,
        "role_quotas": SOURCE_ROLE_QUOTAS,
        "provider_counts": {
            task_id: len({item.provider for item in candidates if item.task_id == task_id}) for task_id in task_ids
        },
        "duplicate_with_prior_snapshots": reused_urls,
        "method_runs_authorized": False,
    }


def write_catalog(
    candidates: tuple[CatalogCandidate, ...],
    output_directory: str | Path,
    *,
    captured_source_ids: frozenset[str] = frozenset(),
    prior_source_files: tuple[Path, ...] = _PRIOR_SOURCE_FILES,
) -> dict[str, object]:
    """Write the validated catalog and a queue for uncaptured candidates."""

    report = validate_catalog(candidates, prior_source_files=prior_source_files)
    root = Path(output_directory)
    root.mkdir(parents=True, exist_ok=True)
    _write_jsonl(root / "dev_source_catalog.jsonl", [item.to_dict() for item in candidates])
    pending = [
        {
            "task_id": item.task_id,
            "source_id": item.source_id,
            "title": item.title,
            "url": item.url,
            "provider": item.provider,
            "capture_locator": item.capture_locator,
            "candidate_role": item.candidate_role,
            "status": "pending_verbatim_capture",
        }
        for item in candidates
        if item.source_id not in captured_source_ids
    ]
    (root / "dev_verbatim_capture_queue.json").write_text(
        json.dumps(
            {
                "status": "pending_verbatim_capture" if pending else "complete",
                "candidate_count": len(candidates),
                "captured_count": len(captured_source_ids),
                "pending_count": len(pending),
                "method_runs_authorized": False,
                "sources": pending,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    report = {
        **report,
        "catalog_path": str(root / "dev_source_catalog.jsonl"),
        "captured_count": len(captured_source_ids),
        "pending_verbatim_capture_count": len(pending),
        "annotation_started": False,
    }
    (root / "dev_source_catalog_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def _load_prior_urls(paths: tuple[Path, ...]) -> set[str]:
    urls: set[str] = set()
    for path in paths:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                urls.add(normalize_url(str(json.loads(line)["url"])))
    return urls


def _required_string(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows) + "\n",
        encoding="utf-8",
    )
