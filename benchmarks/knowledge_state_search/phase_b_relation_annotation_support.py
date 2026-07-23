"""Deterministic packet mapping, consensus, and priority-sampling helpers."""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from benchmarks.knowledge_state_search.phase_b_annotation_packet_contract import (
    PACKET_FIELDS,
    REVIEWERS,
    validate_blind_model_annotation_packets,
)
from benchmarks.knowledge_state_search.phase_b_relation_annotation_contract import (
    RELATION_LABELS,
    ModelRelationJudgment,
    RelationAnnotationInput,
    required_string,
)
from benchmarks.knowledge_state_search.phase_b_relation_target_specs import (
    DEFAULT_DESIGN_DIRECTORY,
    DEFAULT_TARGET_SPECS_PATH,
    DEFAULT_TASK_SCOPES_PATH,
    load_relation_target_specs,
)

CanonicalKey = tuple[str, str, str, str]


@dataclass(frozen=True)
class PacketBundle:
    """Loaded reviewer packets plus private canonical mappings."""

    inputs_by_reviewer: dict[str, tuple[RelationAnnotationInput, ...]]
    canonical_by_blind_id: dict[str, dict[str, CanonicalKey]]
    public_payload_by_key: dict[CanonicalKey, dict[str, str]]
    canonical_keys: tuple[CanonicalKey, ...]


def load_packet_bundle(packet_directory: Path) -> PacketBundle:
    """Load both reviewer packets and verify identical canonical content."""

    validate_blind_model_annotation_packets(packet_directory)
    target_specs = load_relation_target_specs(
        design_directory=DEFAULT_DESIGN_DIRECTORY,
        target_specs_path=DEFAULT_TARGET_SPECS_PATH,
        task_scopes_path=DEFAULT_TASK_SCOPES_PATH,
    )
    inputs_by_reviewer: dict[str, tuple[RelationAnnotationInput, ...]] = {}
    canonical_by_blind_id: dict[str, dict[str, CanonicalKey]] = {}
    public_payload_by_key: dict[CanonicalKey, dict[str, str]] = {}
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
    return PacketBundle(
        inputs_by_reviewer=inputs_by_reviewer,
        canonical_by_blind_id=canonical_by_blind_id,
        public_payload_by_key=public_payload_by_key,
        canonical_keys=tuple(sorted(key_sets["doubao"])),
    )


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
) -> tuple[dict[str, object], ...]:
    """Map blind labels to canonical pairs and route every non-clean agreement."""

    if set(judgments_by_reviewer) != set(REVIEWERS):
        raise ValueError("relation consensus requires Doubao and MiMo judgments")
    judgments_by_key: dict[str, dict[CanonicalKey, ModelRelationJudgment]] = {}
    expected_keys = set(selected_keys)
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
        relation_agreement = doubao.relation == mimo.relation
        exact_judgment_agreement = relation_agreement and doubao.needs_context == mimo.needs_context
        any_needs_context = doubao.needs_context or mimo.needs_context
        if exact_judgment_agreement and not any_needs_context:
            disposition = "dual_model_consensus"
            reason = "same_relation_without_context_flag"
            consensus_relation: str | None = doubao.relation
        else:
            disposition = "priority_subagent_required"
            reason = "context_uncertainty" if any_needs_context else "relation_disagreement"
            consensus_relation = None
        rows.append(
            {
                **canonical_row(key),
                "reviewer_judgments": {
                    "doubao": _judgment_summary(doubao),
                    "mimo": _judgment_summary(mimo),
                },
                "relation_agreement": relation_agreement,
                "exact_judgment_agreement": exact_judgment_agreement,
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
    *,
    random_seed: int,
) -> tuple[list[dict[str, str]], list[dict[str, object]]]:
    """Blind and independently order priority adjudication and spot-check rows."""

    ordered = list(action_rows)
    random.Random(random_seed).shuffle(ordered)
    packet: list[dict[str, str]] = []
    private_map: list[dict[str, object]] = []
    for index, action in enumerate(ordered, 1):
        key = row_key(action)
        priority_blind_item_id = f"p_{index:04d}"
        packet_row = {
            "blind_item_id": priority_blind_item_id,
            **public_payload_by_key[key],
        }
        if tuple(packet_row) != PACKET_FIELDS:
            raise ValueError("priority packet public field contract is invalid")
        packet.append(packet_row)
        private_map.append(
            {
                "priority_blind_item_id": priority_blind_item_id,
                "action_id": required_string(action, "action_id"),
                "action_type": required_string(action, "action_type"),
                **canonical_row(key),
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


def _judgment_summary(judgment: ModelRelationJudgment) -> dict[str, object]:
    return {
        "blind_item_id": judgment.blind_item_id,
        "model": judgment.model,
        "task_scope": judgment.task_scope,
        "proposition_checks": [check.to_dict() for check in judgment.proposition_checks],
        "relation": judgment.relation,
        "needs_context": judgment.needs_context,
        "notes": judgment.notes,
        "input_sha256": judgment.input_sha256,
        "response_id": judgment.response_id,
    }


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
