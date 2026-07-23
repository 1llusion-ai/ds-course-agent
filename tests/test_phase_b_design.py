"""Tests for the pre-source Phase B task-design artifact."""

from __future__ import annotations

import json
from pathlib import Path

from benchmarks.knowledge_state_search.phase_b_design import (
    build_phase_b_design,
    write_phase_b_design,
)


def test_phase_b_design_has_frozen_counts_and_balanced_splits():
    design = build_phase_b_design()

    assert len(design.tasks) == 12
    assert len(design.profiles) == 24
    assert len(design.claims) == 72
    assert len(design.edges) == 48
    assert len(design.splits["phase_b_dev"]) == 3
    assert len(design.splits["phase_b_test"]) == 9

    learner_kinds = {
        task_id: next(
            claim["kind"] for claim in design.claims if claim["task_id"] == task_id and claim["kind"] != "core"
        )
        for task_id in (task["task_id"] for task in design.tasks)
    }
    assert sorted(learner_kinds.values()).count("prerequisite") == 4
    assert sorted(learner_kinds.values()).count("misconception") == 4
    assert sorted(learner_kinds.values()).count("goal") == 4
    assert {learner_kinds[task_id] for task_id in design.splits["phase_b_dev"]} == {
        "prerequisite",
        "misconception",
        "goal",
    }


def test_phase_b_design_profiles_activate_zero_or_one_learner_claim():
    design = build_phase_b_design()

    claims_by_task = {}
    for claim in design.claims:
        if claim["kind"] != "core":
            claims_by_task[claim["task_id"]] = claim

    profiles_by_task: dict[str, list[dict[str, object]]] = {}
    for profile in design.profiles:
        profiles_by_task.setdefault(str(profile["task_id"]), []).append(profile)

    for task_id, profiles in profiles_by_task.items():
        learner = claims_by_task[task_id]
        field = str(learner["profile_condition"]["field"])
        value = str(learner["profile_condition"]["value"])
        active_counts = []
        for profile in profiles:
            if field == "weak_concept":
                active = value in profile["weak_concepts"]
            elif field == "misconception":
                active = value in profile["misconceptions"]
            else:
                active = value == profile["learning_goal"]
            active_counts.append(int(active))
        assert sorted(active_counts) == [0, 1], task_id


def test_phase_b_design_paths_are_two_non_branching_chains_and_include_learner_claim():
    design = build_phase_b_design()

    claims_by_task = {}
    for claim in design.claims:
        claims_by_task.setdefault(claim["task_id"], set()).add(claim["claim_id"])
    edges_by_task: dict[str, list[dict[str, object]]] = {}
    for edge in design.edges:
        edges_by_task.setdefault(str(edge["task_id"]), []).append(edge)

    for task_id, edges in edges_by_task.items():
        assert len(edges) == 4
        paths: dict[str, list[dict[str, object]]] = {}
        for edge in edges:
            for path_id in edge["path_ids"]:
                paths.setdefault(str(path_id), []).append(edge)
        assert len(paths) == 2
        learner_id = f"{task_id}_c06"
        learner_paths = 0
        for path_edges in paths.values():
            assert len(path_edges) >= 2
            outgoing = {edge["from_claim_id"]: edge for edge in path_edges}
            incoming = {edge["to_claim_id"]: edge for edge in path_edges}
            assert len(set(outgoing) & set(incoming)) == len(path_edges) - 1
            path_claims = {path_edges[0]["from_claim_id"], *(edge["to_claim_id"] for edge in path_edges)}
            learner_paths += int(learner_id in path_claims)
            assert path_claims <= claims_by_task[task_id]
        assert learner_paths >= 1


def test_phase_b_design_writer_marks_sources_and_methods_pending(tmp_path: Path):
    output = write_phase_b_design(tmp_path / "design")

    manifest = json.loads((output / "design_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "draft_task_design"
    assert manifest["source_collection_started"] is False
    assert manifest["annotation_started"] is False
    assert manifest["method_runs_authorized"] is False
    assert manifest["counts"] == {
        "tasks": 12,
        "profiles": 24,
        "claims": 72,
        "edges": 48,
        "sources": 0,
        "annotations": 0,
    }
