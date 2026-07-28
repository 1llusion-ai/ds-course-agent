"""Tests for the public-source exploratory dataset adapter."""

from __future__ import annotations

import json
from pathlib import Path

from benchmarks.knowledge_state_search.evidence import EvidenceSnapshot
from benchmarks.knowledge_state_search.gap_planner import KnowledgeStateGapPlanner
from benchmarks.knowledge_state_search.models import SearchTask
from benchmarks.knowledge_state_search.public_data_adapter import build_exploratory_dataset


def test_build_exploratory_dataset_is_claim_level_and_validates(tmp_path: Path) -> None:
    """Build a standalone exploratory snapshot without touching Phase B files."""

    output = tmp_path / "public_data"
    result = build_exploratory_dataset(output_directory=output)

    tasks_payload = json.loads((output / "tasks.json").read_text(encoding="utf-8"))
    tasks = [SearchTask.from_dict(item) for item in tasks_payload["tasks"]]
    snapshot = EvidenceSnapshot.load(output / "snapshot")
    manifest = json.loads((output / "public_data_manifest.json").read_text(encoding="utf-8"))

    assert result["task_count"] == 3
    assert len(tasks) == 3
    assert len(snapshot.sources) == 30
    assert len(snapshot.annotations) == result["annotation_count"] == 46
    assert manifest["label_mode"] == "inherited_exploratory_proxy"
    assert manifest["new_human_annotation_count"] == 0
    assert all(
        claim.kind in {"core", "prerequisite", "misconception", "goal"}
        for task in tasks
        for claim in task.evidence_requirements
    )

    tasks_by_id = {task.task_id: task for task in tasks}
    gd_task = tasks_by_id["gd_learning_rate"]
    gd_profiles = {profile.student_id: profile for profile in gd_task.profiles}
    assert KnowledgeStateGapPlanner().plan(gd_task, gd_profiles["gd_profile_nogap"]).learner_requirements == ()
    assert {
        item.requirement_id
        for item in KnowledgeStateGapPlanner()
        .plan(
            gd_task,
            gd_profiles["gd_profile_prerequisite"],
        )
        .learner_requirements
    } == {"gd_derivative_slope"}

    pr_task = tasks_by_id["pr_vs_roc_imbalance"]
    pr_profiles = {profile.student_id: profile for profile in pr_task.profiles}
    assert KnowledgeStateGapPlanner().plan(pr_task, pr_profiles["pr_profile_nogap"]).learner_requirements == ()
    assert {
        item.requirement_id
        for item in KnowledgeStateGapPlanner()
        .plan(
            pr_task,
            pr_profiles["pr_profile_goal"],
        )
        .learner_requirements
    } == {"pr_threshold_goal"}
