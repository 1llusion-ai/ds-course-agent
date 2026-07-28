"""Validate and consolidate the complete agent-captured Phase B source pool."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from benchmarks.knowledge_state_search.evidence import SnapshotSource
from benchmarks.knowledge_state_search.phase_b_source_qa import (
    excerpt_word_count,
    validate_source_qa,
)
from benchmarks.knowledge_state_search.phase_b_source_shakeout import _PRIOR_SOURCE_FILES

DEFAULT_BATCH_DIRECTORIES = (
    Path("var/artifacts/knowledge_state_search/phase_b_collection"),
    Path("var/artifacts/knowledge_state_search/phase_b_collection_batch2"),
    Path("var/artifacts/knowledge_state_search/phase_b_collection_batch3"),
    Path("var/artifacts/knowledge_state_search/phase_b_collection_batch4"),
)
DEFAULT_DESIGN_TASKS = Path("benchmarks/data/knowledge_state_search_confirmatory_v3_phase_b_design/tasks.jsonl")
DEFAULT_OUTPUT_DIRECTORY = Path("var/artifacts/knowledge_state_search/phase_b_source_collection")
_EXPECTED_BATCH_COUNT = 4
_EXPECTED_TASK_COUNT = 12
_EXPECTED_SOURCES_PER_TASK = 12


def validate_source_collection(
    batch_directories: tuple[Path, ...] = DEFAULT_BATCH_DIRECTORIES,
    *,
    design_tasks_file: Path = DEFAULT_DESIGN_TASKS,
    prior_source_files: tuple[Path, ...] = _PRIOR_SOURCE_FILES,
) -> dict[str, object]:
    """Validate all four source batches without treating them as a frozen dataset."""

    if len(batch_directories) != _EXPECTED_BATCH_COUNT:
        raise ValueError(f"Phase B source collection requires exactly {_EXPECTED_BATCH_COUNT} batches")

    expected_task_ids = _load_expected_task_ids(design_tasks_file)
    prior_files = list(prior_source_files)
    source_rows: list[SnapshotSource] = []
    catalog_rows: list[dict[str, Any]] = []
    batch_reports: list[dict[str, object]] = []
    access_source_ids: set[str] = set()
    role_quotas: dict[str, int] | None = None

    for directory in batch_directories:
        catalog_payloads = tuple(_read_jsonl(directory / "dev_source_catalog.jsonl"))
        source_payloads = tuple(_read_jsonl(directory / "verbatim_sources_dev.jsonl"))
        audit_payloads = tuple(_read_jsonl(directory / "verbatim_capture_audit.jsonl"))
        report = validate_source_qa(
            catalog_payloads,
            source_payloads,
            audit_payloads,
            prior_source_files=tuple(prior_files),
        )
        source_file = directory / "verbatim_sources_dev.jsonl"
        prior_files.append(source_file)
        batch_role_quotas = {str(role): int(count) for role, count in dict(report["role_quotas"]).items()}
        if role_quotas is None:
            role_quotas = batch_role_quotas
        elif role_quotas != batch_role_quotas:
            raise ValueError("Phase B source batches must use one source-role quota contract")
        batch_reports.append(
            {
                "directory": str(directory),
                "task_counts": report["task_counts"],
                "captured_source_count": report["captured_source_count"],
                "pending_human_verification_count": report["pending_human_verification_count"],
                "word_counts": report["all_excerpt_word_counts"],
                "role_quota_pass": report["role_quota_pass"],
            }
        )
        catalog_rows.extend(catalog_payloads)
        source_rows.extend(SnapshotSource.from_dict(payload) for payload in source_payloads)
        access_source_ids.update(_validate_access_report(directory / "url_access_report.json"))

    errors: list[str] = []
    source_ids = [source.source_id for source in source_rows]
    if len(source_ids) != len(set(source_ids)):
        errors.append("source_id values must be unique across all Phase B batches")

    task_counts = Counter(source.task_id for source in source_rows)
    if set(task_counts) != set(expected_task_ids):
        errors.append(
            "captured task IDs must match the Phase B design: "
            f"missing={sorted(set(expected_task_ids) - set(task_counts))}, "
            f"extra={sorted(set(task_counts) - set(expected_task_ids))}"
        )
    wrong_task_counts = {
        task_id: task_counts.get(task_id, 0)
        for task_id in expected_task_ids
        if task_counts.get(task_id, 0) != _EXPECTED_SOURCES_PER_TASK
    }
    if wrong_task_counts:
        errors.append(f"every task must contain 12 captured sources: {wrong_task_counts}")

    expected_source_ids = _expected_source_ids(expected_task_ids)
    if set(source_ids) != expected_source_ids:
        errors.append(
            "captured source IDs must match the deterministic task/source roster: "
            f"missing={sorted(expected_source_ids - set(source_ids))}, "
            f"extra={sorted(set(source_ids) - expected_source_ids)}"
        )

    catalog_by_source = _unique_catalog_rows(catalog_rows, errors)
    if set(catalog_by_source) != set(source_ids):
        errors.append("aggregate catalog IDs must equal aggregate captured source IDs")
    if not access_source_ids.issubset(set(source_ids)):
        errors.append("URL-access reports contain unknown source IDs")
    if errors:
        raise ValueError("; ".join(errors))

    word_counts = [excerpt_word_count(source.text) for source in source_rows]
    missing_access_ids = sorted(set(source_ids) - access_source_ids)
    return {
        "status": "pass_pending_human_verification",
        "batch_count": len(batch_directories),
        "task_count": len(task_counts),
        "source_count": len(source_rows),
        "task_counts": dict(sorted(task_counts.items())),
        "word_count_min": min(word_counts),
        "word_count_max": max(word_counts),
        "checksum_valid_count": len(source_rows),
        "excerpt_match_valid_count": len(source_rows),
        "source_role_composition_audited": True,
        "role_quotas": role_quotas,
        "role_quota_pass": True,
        "recorded_http_200_count": len(access_source_ids),
        "http_access_metadata_missing_count": len(missing_access_ids),
        "http_access_metadata_missing_source_ids": missing_access_ids,
        "human_verified_count": 0,
        "pending_human_verification_count": len(source_rows),
        "annotation_started": False,
        "dataset_frozen": False,
        "method_runs_authorized": False,
        "batch_reports": batch_reports,
    }


def write_source_collection_artifacts(
    batch_directories: tuple[Path, ...] = DEFAULT_BATCH_DIRECTORIES,
    output_directory: Path = DEFAULT_OUTPUT_DIRECTORY,
    *,
    design_tasks_file: Path = DEFAULT_DESIGN_TASKS,
    prior_source_files: tuple[Path, ...] = _PRIOR_SOURCE_FILES,
) -> dict[str, object]:
    """Write a clean aggregate source file, human queue, and collection QA report."""

    report = validate_source_collection(
        batch_directories,
        design_tasks_file=design_tasks_file,
        prior_source_files=prior_source_files,
    )
    sources: list[SnapshotSource] = []
    locators: dict[str, str] = {}
    audits: dict[str, dict[str, Any]] = {}
    for directory in batch_directories:
        sources.extend(
            SnapshotSource.from_dict(payload) for payload in _read_jsonl(directory / "verbatim_sources_dev.jsonl")
        )
        for payload in _read_jsonl(directory / "dev_source_catalog.jsonl"):
            locators[_required_string(payload, "source_id")] = _required_string(payload, "capture_locator")
        for payload in _read_jsonl(directory / "verbatim_capture_audit.jsonl"):
            audits[_required_string(payload, "source_id")] = payload

    sources.sort(key=lambda source: source.source_id)
    pending = [
        {
            "source_id": source.source_id,
            "task_id": source.task_id,
            "title": source.title,
            "url": source.url,
            "capture_locator": locators[source.source_id],
            "status": "pending_human_page_verification",
        }
        for source in sources
    ]
    verification_packet = [
        {
            "packet_id": f"pvr_{index:04d}",
            "source_id": source.source_id,
            "task_id": source.task_id,
            "title": source.title,
            "url": source.url,
            "provider": source.provider,
            "capture_locator": locators[source.source_id],
            "excerpt": source.text,
            "raw_capture_path": _required_string(audits[source.source_id], "raw_capture_path"),
            "verification_text_path": _required_string(audits[source.source_id], "verification_text_path"),
            "agent_status": "agent_verified_pending_human",
            "human_status": "pending",
        }
        for index, source in enumerate(sources, 1)
    ]
    report = {
        **report,
        "human_verification_packet_count": len(verification_packet),
        "human_verification_packet_path": str(output_directory / "human_page_verification_packet.jsonl"),
    }
    output_directory.mkdir(parents=True, exist_ok=True)
    _write_jsonl(
        output_directory / "agent_captured_sources.jsonl",
        [source.to_dict() for source in sources],
    )
    _write_jsonl(
        output_directory / "human_page_verification_packet.jsonl",
        verification_packet,
    )
    (output_directory / "human_verification_queue.json").write_text(
        json.dumps(
            {
                "status": "pending",
                "pending_count": len(pending),
                "annotation_started": False,
                "dataset_frozen": False,
                "method_runs_authorized": False,
                "sources": pending,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (output_directory / "human_page_verification_instructions.md").write_text(
        """# Phase B human page-verification instructions

The packet contains one row per agent-captured source. For each row, open the
canonical `url` and verify the following independently:

1. The page is publicly accessible and corresponds to the recorded title.
2. The `excerpt` is a contiguous verbatim passage from that page or PDF.
3. Punctuation, qualifiers, negations, and mathematical notation are preserved.
4. The `capture_locator` points to the relevant section or page.
5. The excerpt is sufficient to judge its later claim/source relation without
   relying on the discovery preview or candidate metadata.

Record results in a separate JSONL file. Do not edit
`agent_captured_sources.jsonl` or the packet in place. Each result must contain:

```json
{
  "source_id": "pb_tNN_sMM",
  "status": "verified",
  "reviewer_id": "human-reviewer-id",
  "reviewed_at": "2026-07-23T00:00:00+08:00",
  "notes": ""
}
```

Allowed `status` values are `verified`, `repair_needed`, `inaccessible`, and
`needs_context`. A source with any status other than `verified` must be
repaired or replaced before annotation. Do not infer annotation labels during
this review.
""",
        encoding="utf-8",
    )
    (output_directory / "source_collection_qa_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def build_parser() -> argparse.ArgumentParser:
    """Build the complete Phase B source-collection QA CLI."""

    parser = argparse.ArgumentParser(description="Validate the complete agent-captured Phase B source pool.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIRECTORY)
    return parser


def main() -> int:
    """Run aggregate source QA and print its machine-readable report."""

    args = build_parser().parse_args()
    report = write_source_collection_artifacts(output_directory=args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _load_expected_task_ids(path: Path) -> tuple[str, ...]:
    task_ids = tuple(_required_string(payload, "task_id") for payload in _read_jsonl(path))
    if len(task_ids) != _EXPECTED_TASK_COUNT or len(set(task_ids)) != _EXPECTED_TASK_COUNT:
        raise ValueError(f"Phase B design must contain exactly {_EXPECTED_TASK_COUNT} unique tasks")
    return task_ids


def _expected_source_ids(task_ids: tuple[str, ...]) -> set[str]:
    expected: set[str] = set()
    for task_id in task_ids:
        match = re.match(r"^(pb_t\d{2})_", task_id)
        if match is None:
            raise ValueError(f"Phase B task_id has an unsupported source-ID prefix: {task_id}")
        expected.update(f"{match.group(1)}_s{index:02d}" for index in range(1, 13))
    return expected


def _unique_catalog_rows(
    payloads: list[dict[str, Any]],
    errors: list[str],
) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for payload in payloads:
        source_id = _required_string(payload, "source_id")
        if source_id in rows:
            errors.append(f"duplicate aggregate catalog source_id: {source_id}")
        rows[source_id] = payload
    return rows


def _validate_access_report(path: Path) -> set[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("sources")
    if not isinstance(rows, list):
        raise ValueError(f"URL-access report must contain a sources list: {path}")
    source_ids: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"URL-access report rows must be objects: {path}")
        source_id = _required_string(row, "source_id")
        if source_id in source_ids:
            raise ValueError(f"duplicate URL-access source_id in {path}: {source_id}")
        if str(row.get("http_code")) != "200":
            raise ValueError(f"URL-access report contains a non-200 capture: {source_id}")
        source_ids.add(source_id)
    if int(payload.get("checked_count", -1)) != len(rows):
        raise ValueError(f"URL-access checked_count does not match rows: {path}")
    if payload.get("status") != "pass" or payload.get("all_directly_accessible") is not True:
        raise ValueError(f"URL-access report is not passing: {path}")
    return source_ids


def _required_string(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
