"""Load frozen annotation-only atomic relation targets."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from benchmarks.knowledge_state_search.phase_b_relation_annotation_contract import (
    AtomicProposition,
    RelationTargetSpec,
    required_string,
)

DEFAULT_DESIGN_DIRECTORY = Path("benchmarks/data/knowledge_state_search_confirmatory_v3_phase_b_design")
DEFAULT_TARGET_SPECS_PATH = DEFAULT_DESIGN_DIRECTORY / "relation_target_specs.jsonl"


def load_relation_target_specs(
    *,
    design_directory: Path = DEFAULT_DESIGN_DIRECTORY,
    target_specs_path: Path = DEFAULT_TARGET_SPECS_PATH,
) -> dict[tuple[str, str], RelationTargetSpec]:
    """Load and validate annotation-only claim and edge target decompositions."""

    claims = _load_unique_rows(design_directory / "claims.jsonl", "claim_id")
    edges = _load_unique_rows(design_directory / "claim_edges.jsonl", "edge_id")
    claim_specs = _load_unique_rows(target_specs_path, "claim_id")
    if set(claim_specs) != set(claims):
        raise ValueError("relation target specs must cover every Phase B claim exactly")

    result: dict[tuple[str, str], RelationTargetSpec] = {}
    for claim_id, claim in claims.items():
        task_id = required_string(claim, "task_id")
        spec = claim_specs[claim_id]
        if tuple(spec) != ("task_id", "claim_id", "propositions"):
            raise ValueError(f"relation claim spec fields are invalid: {claim_id}")
        if required_string(spec, "task_id") != task_id:
            raise ValueError(f"relation claim spec task mismatch: {claim_id}")
        propositions = _atomic_propositions(spec, claim_id=claim_id)
        result[("claim", claim_id)] = RelationTargetSpec(
            task_id=task_id,
            target_type="claim",
            propositions=propositions,
        )

    for edge_id, edge in edges.items():
        task_id = required_string(edge, "task_id")
        from_claim_id = required_string(edge, "from_claim_id")
        to_claim_id = required_string(edge, "to_claim_id")
        try:
            left_claim = claims[from_claim_id]
            right_claim = claims[to_claim_id]
            left_spec = result[("claim", from_claim_id)]
            right_spec = result[("claim", to_claim_id)]
        except KeyError as exc:
            raise ValueError(f"edge references an unknown relation claim: {edge_id}") from exc
        if required_string(left_claim, "task_id") != task_id or required_string(right_claim, "task_id") != task_id:
            raise ValueError(f"relation edge crosses task boundaries: {edge_id}")
        result[("edge", edge_id)] = RelationTargetSpec(
            task_id=task_id,
            target_type="edge",
            propositions=tuple(
                AtomicProposition(
                    proposition_id=f"left.{proposition.proposition_id}",
                    text=proposition.text,
                )
                for proposition in left_spec.propositions
            )
            + tuple(
                AtomicProposition(
                    proposition_id=f"right.{proposition.proposition_id}",
                    text=proposition.text,
                )
                for proposition in right_spec.propositions
            )
            + (
                AtomicProposition(
                    proposition_id="relation",
                    text=(
                        f"有向关系（{required_string(edge, 'edge_type')}）："
                        f"“{required_string(left_claim, 'description')}” → "
                        f"“{required_string(right_claim, 'description')}”"
                    ),
                ),
            ),
            edge_type=required_string(edge, "edge_type"),
        )
    return result


def load_task_split(
    split_name: str,
    *,
    design_directory: Path = DEFAULT_DESIGN_DIRECTORY,
) -> frozenset[str]:
    """Load one frozen Phase B task split by name."""

    payload = json.loads((design_directory / "splits.json").read_text(encoding="utf-8"))
    splits = payload.get("splits")
    if not isinstance(splits, dict):
        raise ValueError("Phase B splits file lacks a splits object")
    task_ids = splits.get(split_name)
    if not isinstance(task_ids, list) or not task_ids:
        raise ValueError(f"unknown or empty Phase B split: {split_name}")
    if any(not isinstance(task_id, str) or not task_id.strip() for task_id in task_ids):
        raise ValueError(f"Phase B split contains an invalid task ID: {split_name}")
    if len(task_ids) != len(set(task_ids)):
        raise ValueError(f"Phase B split contains duplicate task IDs: {split_name}")
    return frozenset(task_ids)


def _atomic_propositions(
    payload: dict[str, Any],
    *,
    claim_id: str,
) -> tuple[AtomicProposition, ...]:
    raw_propositions = payload.get("propositions")
    if not isinstance(raw_propositions, list) or not raw_propositions:
        raise ValueError(f"relation claim lacks propositions: {claim_id}")
    propositions: list[AtomicProposition] = []
    for index, raw in enumerate(raw_propositions, 1):
        if not isinstance(raw, dict) or tuple(raw) != ("proposition_id", "text"):
            raise ValueError(f"relation proposition fields are invalid: {claim_id}/p{index}")
        proposition_id = required_string(raw, "proposition_id")
        if proposition_id != f"p{index}":
            raise ValueError(f"relation proposition IDs must be consecutive: {claim_id}")
        propositions.append(
            AtomicProposition(
                proposition_id=proposition_id,
                text=required_string(raw, "text"),
            )
        )
    return tuple(propositions)


def _load_unique_rows(path: Path, key_field: str) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(path):
        key = required_string(row, key_field)
        if key in rows:
            raise ValueError(f"duplicate {key_field}: {key}")
        rows[key] = row
    return rows


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
