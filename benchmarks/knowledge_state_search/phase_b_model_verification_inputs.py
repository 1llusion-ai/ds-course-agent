"""Deterministic input construction for Phase B model source verification."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from benchmarks.knowledge_state_search.evidence import SnapshotSource
from benchmarks.knowledge_state_search.phase_b_model_verification_contract import (
    PROMPT_VERSION,
    ReviewInput,
    json_sha256,
    normalize_text,
    required_string,
)

DEFAULT_PACKET_PATH = Path(
    "var/artifacts/knowledge_state_search/phase_b_source_collection/human_page_verification_packet.jsonl"
)
DEFAULT_SOURCES_PATH = Path(
    "var/artifacts/knowledge_state_search/phase_b_source_collection/agent_captured_sources.jsonl"
)
DEFAULT_QA_REPORT_PATH = Path(
    "var/artifacts/knowledge_state_search/phase_b_source_collection/source_collection_qa_report.json"
)


def build_review_inputs(
    packet_path: Path = DEFAULT_PACKET_PATH,
    sources_path: Path = DEFAULT_SOURCES_PATH,
    qa_report_path: Path = DEFAULT_QA_REPORT_PATH,
    *,
    context_characters: int = 900,
) -> tuple[ReviewInput, ...]:
    """Validate captured inputs and build deterministic local context windows."""

    if context_characters < 200:
        raise ValueError("context_characters must be at least 200")
    packet_rows = _read_jsonl(packet_path)
    source_rows = _read_jsonl(sources_path)
    qa_report = json.loads(qa_report_path.read_text(encoding="utf-8"))
    if qa_report.get("status") != "pass_pending_human_verification":
        raise ValueError("source collection QA report is not in the expected passing state")

    packet_by_id = _unique_rows(packet_rows, "packet")
    sources_by_id = _load_sources(source_rows)
    if set(packet_by_id) != set(sources_by_id):
        raise ValueError("verification packet IDs must equal captured source IDs")
    missing_access = {str(source_id) for source_id in qa_report.get("http_access_metadata_missing_source_ids", [])}
    if int(qa_report.get("source_count", -1)) != len(packet_by_id):
        raise ValueError("source collection QA count does not match verification packet")

    inputs: list[ReviewInput] = []
    for source_id in sorted(packet_by_id):
        packet = packet_by_id[source_id]
        source = sources_by_id[source_id]
        _validate_packet_source_match(packet, source)
        verification_path = Path(required_string(packet, "verification_text_path"))
        raw_path = Path(required_string(packet, "raw_capture_path"))
        if not verification_path.is_file():
            raise ValueError(f"verification text is missing: {source_id}")
        if not raw_path.is_file():
            raise ValueError(f"raw capture is missing: {source_id}")
        normalized_page = normalize_text(verification_path.read_text(encoding="utf-8"))
        normalized_excerpt = normalize_text(source.text)
        excerpt_index = normalized_page.find(normalized_excerpt)
        if excerpt_index < 0:
            raise ValueError(f"excerpt is absent from canonical verification text: {source_id}")
        page_context = _context_window(
            normalized_page,
            excerpt_index=excerpt_index,
            excerpt_length=len(normalized_excerpt),
            context_characters=context_characters,
        )
        evidence_anchors = _evidence_anchors(normalized_excerpt)
        capture_locator = required_string(packet, "capture_locator")
        fingerprint_payload = {
            "prompt_version": PROMPT_VERSION,
            "source_id": source_id,
            "title": source.title,
            "url": source.url,
            "provider": source.provider,
            "capture_locator": capture_locator,
            "excerpt": source.text,
            "page_context": page_context,
            "evidence_anchors": dict(evidence_anchors),
            "recorded_http_200": source_id not in missing_access,
        }
        inputs.append(
            ReviewInput(
                source_id=source_id,
                task_id=source.task_id,
                title=source.title,
                url=source.url,
                provider=source.provider,
                capture_locator=capture_locator,
                excerpt=source.text,
                page_context=page_context,
                evidence_anchors=evidence_anchors,
                recorded_http_200=source_id not in missing_access,
                verification_text_path=str(verification_path),
                input_sha256=json_sha256(fingerprint_payload),
            )
        )
    return tuple(inputs)


def interleave_review_inputs(
    inputs: tuple[ReviewInput, ...],
) -> tuple[ReviewInput, ...]:
    """Mix task topics within batches to prevent hidden-topic inference."""

    keyed: list[tuple[int, int, ReviewInput]] = []
    for item in inputs:
        match = re.fullmatch(r"pb_t(\d{2})_s(\d{2})", item.source_id)
        if match is None:
            raise ValueError(f"unsupported Phase B source_id: {item.source_id}")
        keyed.append((int(match.group(2)), int(match.group(1)), item))
    return tuple(item for _, _, item in sorted(keyed))


def _load_sources(rows: list[dict[str, Any]]) -> dict[str, SnapshotSource]:
    sources: dict[str, SnapshotSource] = {}
    for row in rows:
        source = SnapshotSource.from_dict(row)
        if source.source_id in sources:
            raise ValueError(f"duplicate captured source_id: {source.source_id}")
        if source.compute_sha256() != source.sha256:
            raise ValueError(f"captured source checksum mismatch: {source.source_id}")
        sources[source.source_id] = source
    return sources


def _unique_rows(
    rows: list[dict[str, Any]],
    label: str,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        source_id = required_string(row, "source_id")
        if source_id in result:
            raise ValueError(f"duplicate {label} source_id: {source_id}")
        result[source_id] = row
    return result


def _validate_packet_source_match(
    packet: dict[str, Any],
    source: SnapshotSource,
) -> None:
    expected = {
        "task_id": source.task_id,
        "title": source.title,
        "url": source.url,
        "provider": source.provider,
        "excerpt": source.text,
    }
    for field_name, expected_value in expected.items():
        if packet.get(field_name) != expected_value:
            raise ValueError(f"verification packet {field_name} differs from captured source: {source.source_id}")
    if packet.get("agent_status") != "agent_verified_pending_human":
        raise ValueError(f"unexpected agent verification status: {source.source_id}")
    if packet.get("human_status") != "pending":
        raise ValueError(f"model workflow cannot consume claimed human results: {source.source_id}")


def _context_window(
    page: str,
    *,
    excerpt_index: int,
    excerpt_length: int,
    context_characters: int,
) -> str:
    start = max(0, excerpt_index - context_characters)
    end = min(len(page), excerpt_index + excerpt_length + context_characters)
    prefix = "[PAGE START] " if start == 0 else "[EARLIER PAGE CONTENT OMITTED] "
    suffix = " [PAGE END]" if end == len(page) else " [LATER PAGE CONTENT OMITTED]"
    return f"{prefix}{page[start:end]}{suffix}"


def _evidence_anchors(excerpt: str) -> tuple[tuple[str, str], ...]:
    tokens = excerpt.split()
    window_size = min(16, len(tokens))
    starts = (0, max(0, (len(tokens) - window_size) // 2), len(tokens) - window_size)
    anchors: list[tuple[str, str]] = []
    seen: set[str] = set()
    for start in starts:
        text = " ".join(tokens[start : start + window_size])
        if text in seen:
            continue
        seen.add(text)
        anchors.append((f"anchor_{len(anchors) + 1}", text))
    return tuple(anchors)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
