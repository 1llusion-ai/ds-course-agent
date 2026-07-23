"""Validate Phase B blind annotation packet artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = "phase_b_blind_relation_annotation_v1"
ANNOTATORS = ("annotator_a", "annotator_b")
PACKET_FIELDS = (
    "blind_item_id",
    "task_question",
    "target_text",
    "source_title",
    "source_url",
    "source_excerpt",
)
PRIVATE_MAP_FIELDS = (
    "annotator_id",
    "blind_item_id",
    "task_id",
    "target_type",
    "target_id",
    "source_id",
)
FORBIDDEN_PACKET_FIELDS = frozenset(
    {
        "annotation_relation",
        "candidate_role",
        "candidate_targets",
        "claim_id",
        "claim_kind",
        "discovery_preview",
        "discovery_query",
        "doubao_status",
        "edge_id",
        "gold_relation",
        "human_status",
        "mimo_status",
        "model_notes",
        "oracle_query",
        "profile_condition",
        "profile_id",
        "relation",
        "source_id",
        "subagent_status",
        "task_id",
    }
)
_EXPECTED_COUNTS = {
    "tasks": 12,
    "profiles": 24,
    "claims": 72,
    "edges": 48,
    "sources": 144,
    "targets": 120,
    "canonical_pairs": 1440,
    "targets_per_task": 10,
    "pairs_per_annotator": 1440,
    "independent_judgments_required": 2880,
    "labels_populated": 0,
}


def validate_blind_annotation_packets(output_directory: Path) -> dict[str, object]:
    """Validate packet blinding, checksums, coverage, and authorization state."""

    manifest_path = output_directory / "annotation_packet_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("protocol_version") != PROTOCOL_VERSION:
        raise ValueError("annotation packet protocol version is invalid")
    validate_blocked_state(manifest)
    if manifest.get("status") != "ready_for_independent_annotation":
        raise ValueError("annotation packet status is invalid")
    random_seed = manifest.get("random_seed")
    if not isinstance(random_seed, int):
        raise ValueError("annotation packet random_seed must be an integer")
    if tuple(manifest.get("packet_fields", ())) != PACKET_FIELDS:
        raise ValueError("annotation packet public field contract is invalid")
    if tuple(manifest.get("private_map_fields", ())) != PRIVATE_MAP_FIELDS:
        raise ValueError("annotation packet private-map field contract is invalid")
    if manifest.get("independent_ordering") is not True:
        raise ValueError("annotation packet independent_ordering must be true")
    if manifest.get("canonical_pair_sets_equal") is not True:
        raise ValueError("annotation packet canonical pair-set equality must be true")

    instructions = _required_mapping(manifest, "instructions")
    _validate_relative_file(output_directory, instructions, "annotation instructions")
    annotators = _required_mapping(manifest, "annotators")
    canonical_orders: dict[str, list[tuple[str, str, str, str]]] = {}
    item_counts: dict[str, int] = {}
    for annotator_id in ANNOTATORS:
        record = annotators.get(annotator_id)
        if not isinstance(record, dict):
            raise ValueError(f"annotation manifest lacks {annotator_id}")
        packet_path = _validate_relative_file(
            output_directory,
            {"path": record.get("packet_path"), "sha256": record.get("packet_sha256")},
            f"{annotator_id} packet",
        )
        private_path = _validate_relative_file(
            output_directory,
            {"path": record.get("private_map_path"), "sha256": record.get("private_map_sha256")},
            f"{annotator_id} private map",
        )
        packet_rows = _read_jsonl(packet_path)
        private_rows = _read_jsonl(private_path)
        canonical_orders[annotator_id] = _validate_annotator_rows(
            annotator_id,
            packet_rows,
            private_rows,
        )
        item_counts[annotator_id] = len(packet_rows)
        if int(record.get("item_count", -1)) != len(packet_rows):
            raise ValueError(f"{annotator_id} item_count does not match packet rows")
        if int(record.get("ordering_seed", -1)) != derive_ordering_seed(random_seed, annotator_id):
            raise ValueError(f"{annotator_id} ordering seed does not match the recorded master seed")

    if set(canonical_orders["annotator_a"]) != set(canonical_orders["annotator_b"]):
        raise ValueError("annotator A/B packets do not cover the same canonical pairs")
    if canonical_orders["annotator_a"] == canonical_orders["annotator_b"]:
        raise ValueError("annotator A/B packet orders are not independent")

    counts = _required_mapping(manifest, "counts")
    observed_counts = {field: int(counts.get(field, -1)) for field in _EXPECTED_COUNTS}
    if observed_counts != _EXPECTED_COUNTS:
        raise ValueError(f"annotation packet count contract is invalid: {observed_counts}")
    expected_pairs = int(counts.get("pairs_per_annotator", -1))
    if any(count != expected_pairs for count in item_counts.values()):
        raise ValueError("manifest pair count does not match annotator packets")
    if int(counts.get("independent_judgments_required", -1)) != expected_pairs * len(ANNOTATORS):
        raise ValueError("manifest independent-judgment count is invalid")
    if int(counts.get("labels_populated", -1)) != 0 or manifest.get("labels_populated") is not False:
        raise ValueError("blind packet generation must not populate annotation labels")

    source_verification = _required_mapping(manifest, "source_verification")
    if source_verification.get("source_verification_gate_complete") is not True:
        raise ValueError("annotation packet source-verification gate must be complete")
    if source_verification.get("blind_annotation_authorized") is not True:
        raise ValueError("annotation packet source gate must authorize blind annotation")
    if int(source_verification.get("final_source_verified_count", -1)) != _EXPECTED_COUNTS["sources"]:
        raise ValueError("annotation packet final source-verification count is invalid")
    if int(source_verification.get("human_verified_count", -1)) != 0:
        raise ValueError("annotation packet source gate must remain explicitly model-only")

    input_fingerprints = _required_mapping(manifest, "input_fingerprints")
    for name, record in input_fingerprints.items():
        if not isinstance(record, dict):
            raise ValueError(f"input fingerprint record is invalid: {name}")
        path = Path(_required_string(record, "path"))
        if _required_string(record, "sha256") != file_sha256(path):
            raise ValueError(f"input fingerprint mismatch: {name}")

    return {
        "status": "pass",
        "annotator_count": len(ANNOTATORS),
        "pairs_per_annotator": expected_pairs,
        "independent_judgments_required": expected_pairs * len(ANNOTATORS),
        "labels_populated": 0,
        "annotation_started": False,
        "dataset_frozen": False,
        "method_runs_authorized": False,
    }


def validate_blocked_state(payload: dict[str, Any]) -> None:
    """Require annotation, freeze, and method execution to remain unstarted."""

    if payload.get("annotation_started") is not False:
        raise ValueError("annotation_started must remain false during packet generation")
    if payload.get("dataset_frozen") is not False:
        raise ValueError("dataset_frozen must remain false before adjudication")
    if payload.get("method_runs_authorized") is not False:
        raise ValueError("Phase B method runs must remain unauthorized")


def file_sha256(path: Path) -> str:
    """Return the SHA-256 digest for one packet or input file."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def derive_ordering_seed(random_seed: int, annotator_id: str) -> int:
    """Derive one deterministic annotator-specific shuffle seed."""

    digest = hashlib.sha256(f"{random_seed}:{annotator_id}".encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False)


def _validate_annotator_rows(
    annotator_id: str,
    packet_rows: list[dict[str, Any]],
    private_rows: list[dict[str, Any]],
) -> list[tuple[str, str, str, str]]:
    if len(packet_rows) != len(private_rows):
        raise ValueError(f"{annotator_id} packet/private-map row counts differ")
    packet_by_id: dict[str, dict[str, Any]] = {}
    for row in packet_rows:
        if tuple(row) != PACKET_FIELDS or set(row).intersection(FORBIDDEN_PACKET_FIELDS):
            raise ValueError(f"{annotator_id} packet exposes a forbidden or unexpected field")
        blind_item_id = _required_string(row, "blind_item_id")
        if blind_item_id in packet_by_id:
            raise ValueError(f"{annotator_id} contains duplicate blind item IDs")
        for field in PACKET_FIELDS[1:]:
            _required_string(row, field)
        packet_by_id[blind_item_id] = row

    private_ids: set[str] = set()
    canonical_keys: set[tuple[str, str, str, str]] = set()
    canonical_by_blind_id: dict[str, tuple[str, str, str, str]] = {}
    for row in private_rows:
        if tuple(row) != PRIVATE_MAP_FIELDS:
            raise ValueError(f"{annotator_id} private map field contract is invalid")
        if row.get("annotator_id") != annotator_id:
            raise ValueError(f"{annotator_id} private map has an incorrect annotator_id")
        blind_item_id = _required_string(row, "blind_item_id")
        if blind_item_id not in packet_by_id or blind_item_id in private_ids:
            raise ValueError(f"{annotator_id} private map blind IDs are invalid")
        private_ids.add(blind_item_id)
        target_type = _required_string(row, "target_type")
        if target_type not in {"claim", "edge"}:
            raise ValueError(f"{annotator_id} private map target_type is invalid")
        canonical_key = (
            _required_string(row, "task_id"),
            target_type,
            _required_string(row, "target_id"),
            _required_string(row, "source_id"),
        )
        if canonical_key in canonical_keys:
            raise ValueError(f"{annotator_id} private map duplicates a canonical pair")
        canonical_keys.add(canonical_key)
        canonical_by_blind_id[blind_item_id] = canonical_key
    if set(packet_by_id) != private_ids:
        raise ValueError(f"{annotator_id} packet/private-map ID coverage differs")
    return [canonical_by_blind_id[_required_string(row, "blind_item_id")] for row in packet_rows]


def _validate_relative_file(output_directory: Path, record: dict[str, Any], label: str) -> Path:
    relative_path = Path(_required_string(record, "path"))
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError(f"{label} path must stay within the output directory")
    path = output_directory / relative_path
    if _required_string(record, "sha256") != file_sha256(path):
        raise ValueError(f"{label} checksum mismatch")
    return path


def _required_mapping(payload: dict[str, Any], field: str) -> dict[str, Any]:
    value = payload.get(field)
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def _required_string(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"JSONL rows must be objects: {path}")
        rows.append(payload)
    return rows
