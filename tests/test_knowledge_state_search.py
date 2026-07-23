"""Tests for the knowledge-state search validation harness."""

from __future__ import annotations

import json
from pathlib import Path

from benchmarks.knowledge_state_search.analyze_probe import analyze
from benchmarks.knowledge_state_search.gap_planner import KnowledgeStateGapPlanner
from benchmarks.knowledge_state_search.models import SearchTask, StudentProfile
from benchmarks.knowledge_state_search.prompt_probe import (
    _profile_text,
    _profile_view,
    _validate_plan_output,
    build_user_prompt,
)

DATA_PATH = Path("benchmarks/data/knowledge_state_search_probe_v1.json")


def _load_tasks() -> list[SearchTask]:
    payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    return [SearchTask.from_dict(item) for item in payload["tasks"]]


def test_gap_planner_preserves_core_requirements_for_mastered_student():
    task = _load_tasks()[0]
    profile = next(item for item in task.profiles if item.student_id == "kmeans_advanced")

    gap = KnowledgeStateGapPlanner().plan(task, profile)

    assert {item.requirement_id for item in gap.core_requirements} == {
        "core_objective_update",
        "core_local_minimum",
    }
    assert gap.learner_requirements == ()
    assert "初始化" in gap.satisfied_prerequisites


def test_gap_planner_adds_misconception_obligation_without_dropping_core():
    task = _load_tasks()[0]
    profile = next(item for item in task.profiles if item.student_id == "kmeans_misconception")

    gap = KnowledgeStateGapPlanner().plan(task, profile)

    assert {item.requirement_id for item in gap.core_requirements} == {
        "core_objective_update",
        "core_local_minimum",
    }
    assert {item.requirement_id for item in gap.learner_requirements} == {
        "misconception_global_optimum",
        "prereq_initialization",
    }


def test_analyzer_reports_variant_success_and_coverage():
    payload = {
        "results": [
            {
                "task_id": "task",
                "student_id": "student",
                "variant": "gap_planner",
                "error": None,
                "gap": {
                    "core_requirements": [
                        {"concept": "局部最优", "search_terms": ["局部最优"]},
                    ],
                    "learner_requirements": [
                        {"concept": "初始化", "search_terms": ["初始化"]},
                    ],
                },
                "response": {
                    "actions": [
                        {
                            "query": "K-means 初始化与局部最优",
                            "purpose": "解释不同初始化导致不同局部最优",
                            "target_requirements": ["core", "learner"],
                        }
                    ]
                },
            }
        ]
    }

    summary = analyze(payload)

    assert summary["variants"]["gap_planner"]["success_rate"] == 1.0
    assert summary["variants"]["gap_planner"]["core_coverage_mean"] == 1.0
    assert summary["variants"]["gap_planner"]["learner_coverage_mean"] == 1.0


def test_analyzer_keeps_profile_pairs_separate_by_variant():
    base = {
        "task_id": "task",
        "student_id": "student_a",
        "error": None,
        "gap": {"core_requirements": [], "learner_requirements": []},
        "response": {"actions": [{"query": "same", "purpose": "", "target_requirements": []}]},
    }
    payload = {
        "results": [
            {**base, "student_id": "student_a", "variant": "generic"},
            {**base, "student_id": "student_b", "variant": "generic"},
            {
                **base,
                "student_id": "student_a",
                "variant": "gap_planner",
                "response": {"actions": [{"query": "局部最优", "purpose": "", "target_requirements": []}]},
            },
            {
                **base,
                "student_id": "student_b",
                "variant": "gap_planner",
                "response": {"actions": [{"query": "初始化", "purpose": "", "target_requirements": []}]},
            },
        ]
    }

    summary = analyze(payload)

    pairs = summary["paired_profile_differences"]
    assert {(item["variant"], item["different"]) for item in pairs} == {
        ("generic", False),
        ("gap_planner", True),
    }


def test_profile_ablation_view_exposes_only_requested_field():
    profile = StudentProfile(
        student_id="student",
        level="beginner",
        mastered_concepts=("聚类",),
        weak_concepts=("局部最优",),
        misconceptions=("全局最优误解",),
        learning_goal="建立直观理解",
    )

    assert _profile_view(profile, "profile_mastery_only") == {"mastered_concepts": ["聚类"]}
    assert _profile_view(profile, "profile_weak_only") == {"weak_concepts": ["局部最优"]}
    assert _profile_view(profile, "profile_misconception_only") == {"misconceptions": ["全局最优误解"]}
    assert _profile_view(profile, "profile_goal_only") == {"learning_goal": "建立直观理解"}


def test_profile_prompt_does_not_leak_semantic_student_id():
    profile = StudentProfile(
        student_id="kmeans_misconception",
        level="intermediate",
        misconceptions=("全局最优误解",),
    )

    rendered = _profile_text(profile)

    assert "kmeans_misconception" not in rendered
    assert "全局最优误解" in rendered


def test_all_planner_variants_receive_same_core_contract():
    task = _load_tasks()[0]
    profile = task.profiles[0]
    gap = KnowledgeStateGapPlanner().plan(task, profile)

    generic = build_user_prompt(task, profile, variant="generic", gap=gap)
    raw_profile = build_user_prompt(task, profile, variant="profile_prompt", gap=gap)
    structured = build_user_prompt(task, profile, variant="gap_planner", gap=gap)

    for prompt in (generic, raw_profile, structured):
        assert "core_objective_update" in prompt
        assert "core_local_minimum" in prompt
    assert "prereq_initialization" not in generic
    assert "prereq_initialization" not in raw_profile
    assert "prereq_initialization" in structured


def test_unconstrained_gap_prompt_relaxes_only_target_coverage_contract():
    task = _load_tasks()[0]
    profile = next(item for item in task.profiles if item.student_id == "kmeans_misconception")
    gap = KnowledgeStateGapPlanner().plan(task, profile)

    prompt = build_user_prompt(
        task,
        profile,
        variant="gap_planner",
        gap=gap,
        enforce_target_contract=False,
    )

    assert "target_requirements 是可选的" in prompt
    assert "每个 learner_requirements 中的 requirement_id 都必须" not in prompt
    assert "misconception_global_optimum" in prompt


def test_fixed_snapshot_prompt_requires_same_query_language():
    task = _load_tasks()[0]
    profile = task.profiles[0]
    gap = KnowledgeStateGapPlanner().plan(task, profile)

    prompts = [
        build_user_prompt(
            task,
            profile,
            variant=variant,
            gap=gap,
            query_language="英文",
        )
        for variant in ("generic", "profile_prompt", "gap_planner")
    ]

    assert all("query 必须使用英文" in prompt for prompt in prompts)


def test_plan_validation_rejects_requirement_id_outside_contract():
    payload = {
        "actions": [
            {
                "type": "SEARCH",
                "query": "K-means 初始化",
                "purpose": "搜索初始化",
                "target_requirements": ["learner_hidden"],
            }
        ]
    }

    error = _validate_plan_output(payload, ("core_visible",))

    assert error is not None


def test_plan_validation_requires_visible_learner_target_coverage():
    payload = {
        "actions": [
            {
                "type": "SEARCH",
                "query": "gradient descent learning rate stability",
                "purpose": "cover core",
                "target_requirements": ["core_visible"],
            }
        ]
    }

    error = _validate_plan_output(
        payload,
        ("core_visible", "predicted_01"),
        required_target_ids=("predicted_01",),
        query_language="英文",
    )

    assert error is not None


def test_plan_validation_rejects_non_english_query_when_required():
    payload = {
        "actions": [
            {
                "type": "SEARCH",
                "query": "导数与斜率",
                "purpose": "cover learner gap",
                "target_requirements": ["predicted_01"],
            }
        ]
    }

    error = _validate_plan_output(
        payload,
        ("predicted_01",),
        required_target_ids=("predicted_01",),
        query_language="英文",
    )

    assert error is not None


def test_plan_validation_rejects_learner_target_with_unrelated_query():
    payload = {
        "actions": [
            {
                "type": "SEARCH",
                "query": "negative gradient descent direction",
                "purpose": "cover learner gap",
                "target_requirements": ["predicted_01"],
            }
        ]
    }

    error = _validate_plan_output(
        payload,
        ("predicted_01",),
        required_target_ids=("predicted_01",),
        required_query_terms={
            "predicted_01": ("derivative as slope", "rate of change"),
        },
        query_language="英文",
    )

    assert error is not None


def test_plan_validation_accepts_learner_query_with_search_term_overlap():
    payload = {
        "actions": [
            {
                "type": "SEARCH",
                "query": "derivative slope and local rate of change",
                "purpose": "cover learner gap",
                "target_requirements": ["predicted_01"],
            }
        ]
    }

    error = _validate_plan_output(
        payload,
        ("predicted_01",),
        required_target_ids=("predicted_01",),
        required_query_terms={
            "predicted_01": ("derivative as slope", "rate of change"),
        },
        query_language="英文",
    )

    assert error is None
