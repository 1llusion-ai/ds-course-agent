"""Tests for the v3 confirmatory dataset loader and claim-graph contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from benchmarks.knowledge_state_search.confirmatory_schema import (
    CanonicalClaim,
    ClaimKind,
    ConfirmatorySchema,
    LearnerProfile,
    ProfileCondition,
    ProfileField,
    file_sha256,
)

_DATA_FILES = (
    "tasks.jsonl",
    "profiles.jsonl",
    "claims.jsonl",
    "claim_edges.jsonl",
    "sources.jsonl",
    "evidence_annotations.jsonl",
    "splits.json",
    "annotation_audit.json",
)


def _source(payload: dict[str, str]) -> dict[str, str]:
    raw = "\n".join(
        payload[field]
        for field in (
            "source_id",
            "task_id",
            "title",
            "url",
            "provider",
            "captured_at",
            "text",
        )
    )
    return {**payload, "sha256": hashlib.sha256(raw.encode()).hexdigest()}


def _write_jsonl(path: Path, payloads: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(item) for item in payloads) + "\n",
        encoding="utf-8",
    )


def _write_fixture(root: Path, *, missing_pair: bool = False, cyclic: bool = False) -> None:
    tasks = [
        {
            "task_id": "task",
            "question": "Why?",
            "target_concepts": ["concept"],
        }
    ]
    profiles = [
        {
            "task_id": "task",
            "profile_id": "no_gap",
            "level": "intermediate",
            "mastered_concepts": ["gap"],
            "weak_concepts": [],
            "misconceptions": [],
            "learning_goal": "understand",
        },
        {
            "task_id": "task",
            "profile_id": "single_gap",
            "level": "intermediate",
            "mastered_concepts": [],
            "weak_concepts": ["gap"],
            "misconceptions": [],
            "learning_goal": "understand",
        },
    ]
    claims = [
        {
            "task_id": "task",
            "claim_id": "core_a",
            "kind": "core",
            "concept": "a",
            "description": "core a",
            "hard": True,
            "priority": 3,
            "oracle_query": "core a",
            "profile_condition": None,
        },
        {
            "task_id": "task",
            "claim_id": "core_b",
            "kind": "core",
            "concept": "b",
            "description": "core b",
            "hard": True,
            "priority": 3,
            "oracle_query": "core b",
            "profile_condition": None,
        },
        {
            "task_id": "task",
            "claim_id": "gap",
            "kind": "prerequisite",
            "concept": "gap",
            "description": "learner gap",
            "hard": False,
            "priority": 2,
            "oracle_query": "learner gap",
            "profile_condition": {"field": "weak_concept", "value": "gap"},
        },
    ]
    edges = [
        {
            "task_id": "task",
            "edge_id": "edge_1",
            "from_claim_id": "gap",
            "to_claim_id": "core_a",
            "edge_type": "prerequisite",
            "required": True,
            "path_ids": ["path_1"],
        },
        {
            "task_id": "task",
            "edge_id": "edge_2",
            "from_claim_id": "core_a",
            "to_claim_id": "core_b",
            "edge_type": "causal",
            "required": True,
            "path_ids": ["path_1"],
        },
    ]
    if cyclic:
        edges.append(
            {
                "task_id": "task",
                "edge_id": "edge_3",
                "from_claim_id": "core_b",
                "to_claim_id": "gap",
                "edge_type": "explains",
                "required": True,
                "path_ids": [],
            }
        )
    sources = [
        _source(
            {
                "source_id": "source",
                "task_id": "task",
                "title": "Source",
                "url": "https://example.edu/source",
                "provider": "example.edu",
                "captured_at": "2026-07-21T00:00:00+00:00",
                "text": "core a core b learner gap",
            }
        )
    ]
    annotations = []
    targets = [
        ("claim", "core_a"),
        ("claim", "core_b"),
        ("claim", "gap"),
        ("edge", "edge_1"),
        ("edge", "edge_2"),
    ]
    if cyclic:
        targets.append(("edge", "edge_3"))
    for target_type, target_id in targets:
        annotations.append(
            {
                "task_id": "task",
                "target_type": target_type,
                "target_id": target_id,
                "source_id": "source",
                "relation": "supported",
            }
        )
    if missing_pair:
        annotations.pop()
    _write_jsonl(root / "tasks.jsonl", tasks)
    _write_jsonl(root / "profiles.jsonl", profiles)
    _write_jsonl(root / "claims.jsonl", claims)
    _write_jsonl(root / "claim_edges.jsonl", edges)
    _write_jsonl(root / "sources.jsonl", sources)
    _write_jsonl(root / "evidence_annotations.jsonl", annotations)
    (root / "splits.json").write_text(
        json.dumps({"splits": {"pilot": ["task"]}}) + "\n",
        encoding="utf-8",
    )
    (root / "annotation_audit.json").write_text(
        json.dumps(
            {
                "status": "single_pass_pilot",
                "annotators": ["fixture"],
                "adjudicated": False,
                "independently_judged_pairs": 0,
                "notes": "Unit-test fixture only.",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = {
        "benchmark_id": "fixture-v3",
        "schema_version": 3,
        "created_at": "2026-07-21T00:00:00+00:00",
        "source_capture_method": "unit-test fixture",
        "provenance_note": "Synthetic fixture, not benchmark evidence.",
        "task_ids": ["task"],
        "counts": {
            "tasks": len(tasks),
            "profiles": len(profiles),
            "claims": len(claims),
            "edges": len(edges),
            "sources": len(sources),
            "annotations": len(annotations),
        },
        "file_sha256": {filename: file_sha256(root / filename) for filename in _DATA_FILES},
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest) + "\n",
        encoding="utf-8",
    )


def test_confirmatory_schema_loads_fingerprinted_dataset(tmp_path):
    _write_fixture(tmp_path)

    schema = ConfirmatorySchema.load(tmp_path)

    assert schema.manifest.benchmark_id == "fixture-v3"
    assert [claim.claim_id for claim in schema.core_claims("task")] == [
        "core_a",
        "core_b",
    ]
    assert [claim.claim_id for claim in schema.active_learner_claims(schema.profiles_for_task("task")[1])] == ["gap"]


def test_confirmatory_schema_rejects_cycles(tmp_path):
    _write_fixture(tmp_path, cyclic=True)

    with pytest.raises(ValueError, match="cycle"):
        ConfirmatorySchema.load(tmp_path)


def test_confirmatory_schema_requires_exhaustive_annotations(tmp_path):
    _write_fixture(tmp_path, missing_pair=True)

    with pytest.raises(ValueError, match="not exhaustive"):
        ConfirmatorySchema.load(tmp_path)


def test_confirmatory_schema_rejects_fingerprint_mismatch(tmp_path):
    _write_fixture(tmp_path)
    with (tmp_path / "tasks.jsonl").open("a", encoding="utf-8") as file:
        file.write("\n")

    with pytest.raises(ValueError, match="fingerprint mismatch"):
        ConfirmatorySchema.load(tmp_path)


def test_profile_condition_matches_only_typed_trigger():
    profile = LearnerProfile(
        task_id="task",
        profile_id="profile",
        level="intermediate",
        mastered_concepts=("known",),
        weak_concepts=("gap",),
        misconceptions=("wrong",),
        learning_goal="derive",
    )

    assert ProfileCondition(ProfileField.WEAK_CONCEPT, "gap").matches(profile)
    assert ProfileCondition(ProfileField.MISCONCEPTION, "wrong").matches(profile)
    assert ProfileCondition(ProfileField.LEARNING_GOAL, "derive").matches(profile)
    assert not ProfileCondition(ProfileField.MASTERED_CONCEPT, "gap").matches(profile)


def test_learner_claim_requires_kind_aligned_trigger(tmp_path):
    _write_fixture(tmp_path)
    claims_path = tmp_path / "claims.jsonl"
    claims = [json.loads(line) for line in claims_path.read_text(encoding="utf-8").splitlines() if line]
    claims[-1]["profile_condition"]["field"] = "learning_goal"
    _write_jsonl(claims_path, claims)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    manifest["file_sha256"]["claims.jsonl"] = file_sha256(claims_path)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="trigger field"):
        ConfirmatorySchema.load(tmp_path)


def test_direct_claim_construction_uses_typed_profile_condition():
    claim = CanonicalClaim(
        task_id="task",
        claim_id="gap",
        kind=ClaimKind.PREREQUISITE,
        concept="gap",
        description="gap",
        hard=False,
        priority=2,
        oracle_query="gap query",
        profile_condition=ProfileCondition(ProfileField.WEAK_CONCEPT, "gap"),
    )

    assert claim.profile_condition is not None
    assert claim.profile_condition.field is ProfileField.WEAK_CONCEPT
