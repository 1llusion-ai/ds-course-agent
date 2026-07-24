"""Deterministic packet mapping, consensus, and priority-sampling helpers."""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, TypeAlias

from benchmarks.knowledge_state_search.phase_b_annotation_packet_contract import (
    REVIEWERS,
    file_sha256,
    validate_blind_model_annotation_packets,
)
from benchmarks.knowledge_state_search.phase_b_relation_annotation_contract import (
    RELATION_LABELS,
    ModelRelationJudgment,
    RelationAnnotationInput,
    RelationTargetSpec,
    derive_relation,
    required_string,
)
from benchmarks.knowledge_state_search.phase_b_relation_target_specs import (
    DEFAULT_DESIGN_DIRECTORY,
    DEFAULT_TARGET_SPECS_PATH,
    load_relation_target_specs,
)
from benchmarks.knowledge_state_search.phase_b_source_scope_annotation_contract import (
    TASK_SCOPE_LABEL_SET,
)

CanonicalKey = tuple[str, str, str, str]
DEFAULT_SOURCE_SCOPE_LABELS_PATH = Path(
    "var/artifacts/knowledge_state_search/"
    "phase_b_source_scope_dual_model_annotation/"
    "model_proxy_source_scope_labels.jsonl"
)
DEFAULT_SOURCE_SCOPE_REPORT_PATH = DEFAULT_SOURCE_SCOPE_LABELS_PATH.parent / "priority_adjudication_report.json"
SOURCE_SCOPE_LABEL_FIELDS = ("task_id", "source_id", "task_scope")
EXPECTED_FULL_SOURCE_SCOPE_LABEL_COUNT = 144
PRIORITY_PACKET_FIELDS = (
    "blind_item_id",
    "task_question",
    "target_text",
    "target_type",
    "atomic_propositions",
    "edge_type",
    "source_title",
    "source_url",
    "source_excerpt",
    "fixed_task_scope",
)


@dataclass(frozen=True, order=True)
class SourceScopeKey:
    """Canonical identity for one task-specific source scope label."""

    task_id: str
    source_id: str


ResolvedSourceScopeLabels: TypeAlias = Mapping[SourceScopeKey, str]


@dataclass(frozen=True)
class PacketBundle:
    """Loaded reviewer packets plus private canonical mappings."""

    inputs_by_reviewer: dict[str, tuple[RelationAnnotationInput, ...]]
    canonical_by_blind_id: dict[str, dict[str, CanonicalKey]]
    public_payload_by_key: dict[CanonicalKey, dict[str, str]]
    target_spec_by_key: Mapping[CanonicalKey, RelationTargetSpec]
    canonical_keys: tuple[CanonicalKey, ...]
    source_scope_by_key: ResolvedSourceScopeLabels


def load_source_scope_labels(
    path: Path = DEFAULT_SOURCE_SCOPE_LABELS_PATH,
    *,
    expected_count: int = EXPECTED_FULL_SOURCE_SCOPE_LABEL_COUNT,
) -> ResolvedSourceScopeLabels:
    """Load strict finalized source-level task-scope labels."""

    if expected_count < 1:
        raise ValueError("expected source scope label count must be positive")
    rows = _read_jsonl(path)
    if not rows:
        raise ValueError("source scope labels must not be empty")
    labels: dict[SourceScopeKey, str] = {}
    for row in rows:
        if tuple(row) != SOURCE_SCOPE_LABEL_FIELDS:
            raise ValueError("source scope label field contract is invalid")
        key = SourceScopeKey(
            task_id=required_string(row, "task_id"),
            source_id=required_string(row, "source_id"),
        )
        if key in labels:
            raise ValueError(f"source scope labels contain a duplicate key: {key}")
        task_scope = required_string(row, "task_scope")
        if task_scope not in TASK_SCOPE_LABEL_SET:
            raise ValueError(f"source scope label is invalid for {key}: {task_scope}")
        labels[key] = task_scope
    if len(labels) != expected_count:
        raise ValueError(f"source scope labels must contain exactly {expected_count} rows, found {len(labels)}")
    return MappingProxyType(labels)


def load_packet_bundle(
    packet_directory: Path,
    *,
    source_scope_labels_path: Path = DEFAULT_SOURCE_SCOPE_LABELS_PATH,
    source_scope_report_path: Path = DEFAULT_SOURCE_SCOPE_REPORT_PATH,
    expected_source_scope_count: int = EXPECTED_FULL_SOURCE_SCOPE_LABEL_COUNT,
) -> PacketBundle:
    """Load both reviewer packets and verify identical canonical content."""

    validate_blind_model_annotation_packets(packet_directory)
    target_specs = load_relation_target_specs(
        design_directory=DEFAULT_DESIGN_DIRECTORY,
        target_specs_path=DEFAULT_TARGET_SPECS_PATH,
    )
    inputs_by_reviewer: dict[str, tuple[RelationAnnotationInput, ...]] = {}
    canonical_by_blind_id: dict[str, dict[str, CanonicalKey]] = {}
    public_payload_by_key: dict[CanonicalKey, dict[str, str]] = {}
    target_spec_by_key: dict[CanonicalKey, RelationTargetSpec] = {}
    key_sets: dict[str, set[CanonicalKey]] = {}
    for reviewer_id in REVIEWERS:
        packet_rows = _read_jsonl(packet_directory / "packets" / f"{reviewer_id}.jsonl")
        private_rows = _read_jsonl(packet_directory / "data_lead_private" / f"{reviewer_id}_id_map.jsonl")
        private_by_id = {required_string(row, "blind_item_id"): canonical_key(row) for row in private_rows}
        packet_by_id = {required_string(row, "blind_item_id"): row for row in packet_rows}
        if len(packet_by_id) != len(packet_rows):
            raise ValueError(f"{reviewer_id} packet contains duplicate blind IDs")
        input_by_id: dict[str, RelationAnnotationInput] = {}
        for blind_item_id, packet_row in packet_by_id.items():
            key = private_by_id.get(blind_item_id)
            if key is None:
                raise ValueError(f"{reviewer_id} packet/private map coverage differs")
            try:
                target_spec = target_specs[(key[1], key[2])]
            except KeyError as exc:
                raise ValueError(f"missing relation target spec: {key}") from exc
            if target_spec.task_id != key[0]:
                raise ValueError(f"relation target spec task mismatch: {key}")
            existing_target_spec = target_spec_by_key.get(key)
            if existing_target_spec is not None and existing_target_spec != target_spec:
                raise ValueError(f"reviewer packets disagree on relation target spec: {key}")
            target_spec_by_key[key] = target_spec
            input_by_id[blind_item_id] = RelationAnnotationInput.from_packet_row(
                packet_row,
                target_spec,
            )
        if set(input_by_id) != set(private_by_id):
            raise ValueError(f"{reviewer_id} packet/private map coverage differs")
        inputs_by_reviewer[reviewer_id] = tuple(input_by_id.values())
        canonical_by_blind_id[reviewer_id] = private_by_id
        key_sets[reviewer_id] = set(private_by_id.values())
        for blind_item_id, key in private_by_id.items():
            packet_row = packet_by_id[blind_item_id]
            payload_without_id = {field: value for field, value in packet_row.items() if field != "blind_item_id"}
            existing = public_payload_by_key.get(key)
            if existing is not None and existing != payload_without_id:
                raise ValueError(f"reviewer packets disagree on public content: {key}")
            public_payload_by_key[key] = payload_without_id
    if key_sets["doubao"] != key_sets["mimo"]:
        raise ValueError("Doubao/MiMo private maps cover different canonical pairs")
    canonical_keys = tuple(sorted(key_sets["doubao"]))
    source_scope_by_key = load_source_scope_labels(
        source_scope_labels_path,
        expected_count=expected_source_scope_count,
    )
    validate_source_scope_provenance(
        labels_path=source_scope_labels_path,
        report_path=source_scope_report_path,
        expected_count=expected_source_scope_count,
    )
    _validate_source_scope_coverage(canonical_keys, source_scope_by_key)
    return PacketBundle(
        inputs_by_reviewer=inputs_by_reviewer,
        canonical_by_blind_id=canonical_by_blind_id,
        public_payload_by_key=public_payload_by_key,
        target_spec_by_key=MappingProxyType(target_spec_by_key),
        canonical_keys=canonical_keys,
        source_scope_by_key=source_scope_by_key,
    )


def validate_source_scope_provenance(
    *,
    labels_path: Path,
    report_path: Path,
    expected_count: int = EXPECTED_FULL_SOURCE_SCOPE_LABEL_COUNT,
) -> dict[str, object]:
    """Validate the terminal source-scope report and its complete hash chain."""

    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise ValueError("source scope provenance report must be an object")
    required_values = {
        "status": "model_proxy_source_scope_annotation_complete",
        "annotation_basis": "dual_model_consensus_plus_priority_subagent",
        "model_only_proxy": True,
        "human_verified_count": 0,
        "priority_decision_is_terminal": True,
        "no_recursive_model_review": True,
        "unresolved_context_count": 0,
        "model_proxy_labels_finalized": expected_count,
        "full_model_proxy_annotation_complete": True,
    }
    for field_name, expected_value in required_values.items():
        if report.get(field_name) != expected_value:
            raise ValueError(f"source scope provenance report field is invalid: {field_name}")
    artifact_hashes = report.get("artifact_hashes")
    if not isinstance(artifact_hashes, dict):
        raise ValueError("source scope provenance report lacks artifact hashes")
    artifact_paths = {
        "consensus_sha256": report_path.parent / "dual_model_scope_consensus.jsonl",
        "action_manifest_sha256": report_path.parent / "priority_action_manifest.json",
        "action_map_sha256": report_path.parent / "data_lead_priority_action_map.jsonl",
        "priority_results_sha256": report_path.parent / "priority_subagent_results.jsonl",
        "final_labels_sha256": labels_path,
        "unresolved_sha256": report_path.parent / "priority_unresolved_queue.jsonl",
    }
    for hash_field, artifact_path in artifact_paths.items():
        if artifact_hashes.get(hash_field) != file_sha256(artifact_path):
            raise ValueError(f"source scope provenance artifact hash mismatch: {hash_field}")
    return report


def select_canonical_keys(
    keys: tuple[CanonicalKey, ...],
    *,
    limit_pairs: int | None,
    seed: str,
) -> tuple[CanonicalKey, ...]:
    """Select a deterministic task-interleaved subset for smoke or full runs."""

    if limit_pairs is None:
        return keys
    if limit_pairs < 1 or limit_pairs > len(keys):
        raise ValueError("limit_pairs must be between 1 and the available pair count")
    by_task: dict[str, list[CanonicalKey]] = defaultdict(list)
    for key in keys:
        by_task[key[0]].append(key)
    for task_keys in by_task.values():
        task_keys.sort(key=lambda key: key_rank(seed, key))
    selected: list[CanonicalKey] = []
    task_ids = sorted(by_task)
    index = 0
    while len(selected) < limit_pairs:
        progressed = False
        for task_id in task_ids:
            task_keys = by_task[task_id]
            if index < len(task_keys):
                selected.append(task_keys[index])
                progressed = True
                if len(selected) == limit_pairs:
                    break
        if not progressed:
            break
        index += 1
    return tuple(sorted(selected))


def resolve_relation_consensus(
    selected_keys: tuple[CanonicalKey, ...],
    judgments_by_reviewer: dict[str, tuple[ModelRelationJudgment, ...]],
    canonical_by_blind_id: dict[str, dict[str, CanonicalKey]],
    source_scope_by_key: ResolvedSourceScopeLabels,
) -> tuple[dict[str, object], ...]:
    """Resolve relations from structural checks under fixed source-level scope."""

    if set(judgments_by_reviewer) != set(REVIEWERS):
        raise ValueError("relation consensus requires Doubao and MiMo judgments")
    judgments_by_key: dict[str, dict[CanonicalKey, ModelRelationJudgment]] = {}
    expected_keys = set(selected_keys)
    missing_scope_keys = {
        source_scope_key(key) for key in selected_keys if source_scope_key(key) not in source_scope_by_key
    }
    if missing_scope_keys:
        raise ValueError(f"fixed source scope labels are missing selected relation keys: {sorted(missing_scope_keys)}")
    for reviewer_id in REVIEWERS:
        mapped: dict[CanonicalKey, ModelRelationJudgment] = {}
        for judgment in judgments_by_reviewer[reviewer_id]:
            try:
                key = canonical_by_blind_id[reviewer_id][judgment.blind_item_id]
            except KeyError as exc:
                raise ValueError(f"{reviewer_id} judgment references an unknown blind item") from exc
            if key in mapped:
                raise ValueError(f"{reviewer_id} duplicates a canonical relation pair")
            mapped[key] = judgment
        if set(mapped) != expected_keys:
            raise ValueError(f"{reviewer_id} relation coverage mismatch")
        judgments_by_key[reviewer_id] = mapped

    rows: list[dict[str, object]] = []
    for key in selected_keys:
        doubao = judgments_by_key["doubao"][key]
        mimo = judgments_by_key["mimo"][key]
        fixed_task_scope = source_scope_by_key[source_scope_key(key)]
        if fixed_task_scope not in TASK_SCOPE_LABEL_SET:
            raise ValueError(f"fixed source scope label is invalid for {source_scope_key(key)}")
        doubao_relation = derive_relation(
            target_type=key[1],
            task_scope=fixed_task_scope,
            proposition_checks=doubao.proposition_checks,
        )
        mimo_relation = derive_relation(
            target_type=key[1],
            task_scope=fixed_task_scope,
            proposition_checks=mimo.proposition_checks,
        )
        doubao_scope_conflict = _has_source_scope_relation_conflict(
            fixed_task_scope,
            doubao,
        )
        mimo_scope_conflict = _has_source_scope_relation_conflict(
            fixed_task_scope,
            mimo,
        )
        any_scope_conflict = doubao_scope_conflict or mimo_scope_conflict
        relation_agreement = doubao_relation == mimo_relation
        routing_agreement = relation_agreement and doubao.needs_context == mimo.needs_context
        any_needs_context = doubao.needs_context or mimo.needs_context
        if any_scope_conflict:
            disposition = "source_scope_repair_required"
            reason = "source_scope_relation_conflict"
            consensus_relation = None
        elif routing_agreement and not any_needs_context:
            disposition = "dual_model_consensus"
            reason = "same_relation_without_context_flag"
            consensus_relation: str | None = doubao_relation
        else:
            disposition = "priority_subagent_required"
            reason = "context_uncertainty" if any_needs_context else "relation_disagreement"
            consensus_relation = None
        rows.append(
            {
                **canonical_row(key),
                "reviewer_judgments": {
                    "doubao": judgment_summary(
                        doubao,
                        fixed_task_scope=fixed_task_scope,
                        derived_relation=doubao_relation,
                        source_scope_conflict=doubao_scope_conflict,
                    ),
                    "mimo": judgment_summary(
                        mimo,
                        fixed_task_scope=fixed_task_scope,
                        derived_relation=mimo_relation,
                        source_scope_conflict=mimo_scope_conflict,
                    ),
                },
                "source_scope_relation_conflict": any_scope_conflict,
                "relation_agreement": relation_agreement,
                "routing_agreement": routing_agreement,
                "consensus_relation": consensus_relation,
                "disposition": disposition,
                "reason": reason,
                "human_verified": False,
                "model_only_proxy": True,
            }
        )
    return tuple(rows)


def select_priority_spot_check_keys(
    consensus_rows: tuple[dict[str, object], ...],
    *,
    fraction: float,
    seed: str,
) -> tuple[CanonicalKey, ...]:
    """Select a deterministic stratified sample from clean model agreements."""

    if not 0.0 <= fraction <= 1.0:
        raise ValueError("spot-check fraction must be between 0 and 1")
    eligible = [row for row in consensus_rows if row.get("disposition") == "dual_model_consensus"]
    target_count = math.ceil(len(eligible) * fraction)
    if target_count == 0:
        return ()
    ranked = sorted(eligible, key=lambda row: key_rank(seed, row_key(row)))
    strata: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in ranked:
        strata[
            (
                required_string(row, "task_id"),
                required_string(row, "consensus_relation"),
            )
        ].append(row)
    selected: list[dict[str, object]] = []
    if target_count >= len(strata):
        selected.extend(rows[0] for _, rows in sorted(strata.items()))
    selected_keys = {row_key(row) for row in selected}
    for row in ranked:
        if len(selected) == target_count:
            break
        key = row_key(row)
        if key not in selected_keys:
            selected.append(row)
            selected_keys.add(key)
    return tuple(sorted(row_key(row) for row in selected))


def build_priority_action_packet(
    action_rows: tuple[dict[str, object], ...],
    public_payload_by_key: dict[CanonicalKey, dict[str, str]],
    target_spec_by_key: Mapping[CanonicalKey, RelationTargetSpec],
    source_scope_by_key: ResolvedSourceScopeLabels,
    *,
    random_seed: int,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Blind and independently order priority adjudication and spot-check rows."""

    ordered = list(action_rows)
    random.Random(random_seed).shuffle(ordered)
    packet: list[dict[str, object]] = []
    private_map: list[dict[str, object]] = []
    for index, action in enumerate(ordered, 1):
        key = row_key(action)
        try:
            fixed_task_scope = source_scope_by_key[source_scope_key(key)]
        except KeyError as exc:
            raise ValueError(f"priority action lacks fixed source scope: {key}") from exc
        if fixed_task_scope not in TASK_SCOPE_LABEL_SET:
            raise ValueError(f"priority action has invalid fixed source scope: {key}")
        try:
            target_spec = target_spec_by_key[key]
        except KeyError as exc:
            raise ValueError(f"priority action lacks relation target spec: {key}") from exc
        if target_spec.task_id != key[0] or target_spec.target_type != key[1]:
            raise ValueError(f"priority action target spec mismatch: {key}")
        public_payload = public_payload_by_key[key]
        priority_blind_item_id = f"p_{index:04d}"
        packet_row = {
            "blind_item_id": priority_blind_item_id,
            "task_question": public_payload["task_question"],
            "target_text": public_payload["target_text"],
            **target_spec.prompt_fields(),
            "source_title": public_payload["source_title"],
            "source_url": public_payload["source_url"],
            "source_excerpt": public_payload["source_excerpt"],
            "fixed_task_scope": fixed_task_scope,
        }
        if tuple(packet_row) != PRIORITY_PACKET_FIELDS:
            raise ValueError("priority packet public field contract is invalid")
        packet.append(packet_row)
        private_map.append(
            {
                "priority_blind_item_id": priority_blind_item_id,
                "action_id": required_string(action, "action_id"),
                "action_type": required_string(action, "action_type"),
                **canonical_row(key),
                "fixed_task_scope": fixed_task_scope,
                "lower_priority_judgments": action["reviewer_judgments"],
            }
        )
    return packet, private_map


def cohen_kappa(label_pairs: list[tuple[str, str]]) -> float:
    """Compute unweighted Cohen's kappa for the five-way relation labels."""

    if not label_pairs:
        return 0.0
    total = len(label_pairs)
    observed = sum(first == second for first, second in label_pairs) / total
    first_counts = Counter(first for first, _ in label_pairs)
    second_counts = Counter(second for _, second in label_pairs)
    expected = sum((first_counts[label] / total) * (second_counts[label] / total) for label in RELATION_LABELS)
    if expected == 1.0:
        return 1.0
    return (observed - expected) / (1.0 - expected)


def canonical_key(payload: dict[str, Any]) -> CanonicalKey:
    """Return the canonical task-target-source identity from one private row."""

    return (
        required_string(payload, "task_id"),
        required_string(payload, "target_type"),
        required_string(payload, "target_id"),
        required_string(payload, "source_id"),
    )


def canonical_row(key: CanonicalKey) -> dict[str, str]:
    """Serialize one canonical identity."""

    return {
        "task_id": key[0],
        "target_type": key[1],
        "target_id": key[2],
        "source_id": key[3],
    }


def row_key(row: dict[str, Any]) -> CanonicalKey:
    """Return the canonical identity from one consensus or action row."""

    return canonical_key(row)


def key_rank(seed: str, key: CanonicalKey) -> str:
    """Return a deterministic random-looking rank for one canonical pair."""

    return hashlib.sha256(f"{seed}:{'|'.join(key)}".encode()).hexdigest()


def source_scope_key(key: CanonicalKey) -> SourceScopeKey:
    """Return the source-level scope identity for one relation pair."""

    return SourceScopeKey(task_id=key[0], source_id=key[3])


def judgment_summary(
    judgment: ModelRelationJudgment,
    *,
    fixed_task_scope: str,
    derived_relation: str,
    source_scope_conflict: bool,
) -> dict[str, object]:
    return {
        "blind_item_id": judgment.blind_item_id,
        "model": judgment.model,
        "fixed_task_scope": fixed_task_scope,
        "source_scope_conflict": source_scope_conflict,
        "proposition_checks": [check.to_dict() for check in judgment.proposition_checks],
        "relation": derived_relation,
        "needs_context": judgment.needs_context,
        "notes": judgment.notes,
        "input_sha256": judgment.input_sha256,
        "response_id": judgment.response_id,
    }


def _has_source_scope_relation_conflict(
    fixed_task_scope: str,
    judgment: ModelRelationJudgment,
) -> bool:
    return fixed_task_scope == "out_of_scope" and any(check.status != "absent" for check in judgment.proposition_checks)


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


def _validate_source_scope_coverage(
    canonical_keys: tuple[CanonicalKey, ...],
    source_scope_by_key: ResolvedSourceScopeLabels,
) -> None:
    packet_scope_keys = {source_scope_key(key) for key in canonical_keys}
    label_keys = set(source_scope_by_key)
    missing = packet_scope_keys - label_keys
    if missing:
        raise ValueError(f"source scope labels are missing benchmark packet keys: {sorted(missing)}")
    extra = label_keys - packet_scope_keys
    if extra:
        raise ValueError(f"source scope labels contain extra keys not referenced by benchmark packets: {sorted(extra)}")
