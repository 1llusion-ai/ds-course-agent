"""Tests for predicted learner obligation probing."""

from __future__ import annotations

import json
from pathlib import Path

from benchmarks.knowledge_state_search.controlled_profiles import controlled_profiles
from benchmarks.knowledge_state_search.gap_planner import KnowledgeStateGapPlanner
from benchmarks.knowledge_state_search.models import SearchTask
from benchmarks.knowledge_state_search.predicted_gap import (
    _coalesce_goal_obligations,
    _is_retryable_status,
    _retry_delay,
    _validate_prediction,
    _validate_prediction_for_profile,
    predicted_gap,
    prediction_matches_gold,
)

DATA_PATH = Path("benchmarks/data/knowledge_state_search_probe_v1.json")


def _load_tasks() -> list[SearchTask]:
    payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    return [SearchTask.from_dict(item) for item in payload["tasks"]]


def test_controlled_profiles_differ_by_one_learner_factor():
    task = _load_tasks()[0]
    no_gap, single_gap = controlled_profiles(task)

    assert no_gap.weak_concepts == ()
    assert no_gap.misconceptions == ()
    assert len(single_gap.weak_concepts) == 1
    assert no_gap.mastered_concepts != single_gap.mastered_concepts


def test_controlled_profiles_cover_prerequisite_misconception_and_goal():
    tasks = {task.task_id: task for task in _load_tasks()}
    planner = KnowledgeStateGapPlanner()

    observed = {
        task_id: planner.plan(task, controlled_profiles(task)[1]).learner_requirements[0].kind
        for task_id, task in tasks.items()
    }

    assert observed == {
        "kmeans_initialization": "prerequisite",
        "overfitting_generalization": "misconception",
        "pca_covariance": "goal",
        "svm_kernel": "prerequisite",
    }


def test_predicted_gap_does_not_require_gold_requirement_ids():
    task = _load_tasks()[0]
    gap = predicted_gap(
        task,
        {
            "obligations": [
                {
                    "kind": "prerequisite",
                    "concept": "初始化",
                    "claim": "不同初始化可能导致不同结果",
                    "search_terms": ["initialization different outcomes"],
                    "trigger": {"field": "weak_concept", "value": "初始化"},
                    "priority": 2,
                }
            ]
        },
    )

    assert gap.learner_requirements[0].requirement_id == "predicted_01"
    assert gap.learner_requirements[0].requirement_id not in {
        item.requirement_id for item in task.evidence_requirements
    }


def test_prediction_matching_is_evaluation_only():
    task = _load_tasks()[0]
    profile = controlled_profiles(task)[1]
    gold = KnowledgeStateGapPlanner().plan(task, profile)
    predicted = predicted_gap(
        task,
        {
            "obligations": [
                {
                    "kind": "prerequisite",
                    "concept": "初始化",
                    "claim": "不同初始中心会影响收敛结果",
                    "search_terms": ["initialization convergence"],
                    "trigger": {"field": "weak_concept", "value": "初始化"},
                    "priority": 2,
                }
            ]
        },
    )

    score = prediction_matches_gold(predicted, gold)

    assert score["predicted_count"] == 1
    assert score["gold_count"] >= 1
    assert score["recall"] is not None


def test_prediction_schema_rejects_gold_ids():
    error = _validate_prediction(
        {
            "obligations": [
                {
                    "kind": "prerequisite",
                    "concept": "初始化",
                    "claim": "补充初始化解释",
                    "search_terms": ["initialization"],
                    "trigger": {"field": "weak_concept", "value": "初始化"},
                    "requirement_id": "gold_requirement",
                }
            ]
        }
    )

    assert error is not None


def test_prediction_normalizer_coalesces_multiple_goal_obligations_for_one_trigger():
    obligation = {
        "kind": "goal",
        "concept": "公式",
        "claim": "补充公式解释",
        "search_terms": ["formal derivation"],
        "trigger": {"field": "learning_goal", "value": "理解公式和推导"},
    }

    normalized = _coalesce_goal_obligations({"obligations": [obligation, {**obligation, "concept": "推导"}]})

    assert len(normalized["obligations"]) == 1
    assert _validate_prediction(normalized) is None


def test_generic_learning_goal_cannot_trigger_goal_obligation():
    profile = controlled_profiles(_load_tasks()[1])[1]
    error = _validate_prediction_for_profile(
        {
            "obligations": [
                {
                    "kind": "goal",
                    "concept": "算法原理理解",
                    "claim": "解释原理",
                    "search_terms": ["algorithm principles"],
                    "trigger": {"field": "learning_goal", "value": "理解算法原理"},
                }
            ]
        },
        profile,
    )

    assert error is not None


def test_formula_learning_goal_can_trigger_goal_obligation():
    profile = controlled_profiles(_load_tasks()[2])[1]
    error = _validate_prediction_for_profile(
        {
            "obligations": [
                {
                    "kind": "goal",
                    "concept": "formalism",
                    "claim": "补充公式推导",
                    "search_terms": ["eigendecomposition projection"],
                    "trigger": {"field": "learning_goal", "value": profile.learning_goal},
                }
            ]
        },
        profile,
    )

    assert error is None


def test_explicit_business_goal_can_trigger_against_frozen_neutral_goal():
    profile = controlled_profiles(_load_tasks()[2])[1]
    profile = type(profile)(
        student_id=profile.student_id,
        level=profile.level,
        mastered_concepts=profile.mastered_concepts,
        weak_concepts=profile.weak_concepts,
        misconceptions=profile.misconceptions,
        learning_goal="比较阈值并选择业务操作点",
    )
    error = _validate_prediction_for_profile(
        {
            "obligations": [
                {
                    "kind": "goal",
                    "concept": "threshold operating point",
                    "claim": "比较阈值的 precision-recall 权衡",
                    "search_terms": ["classification threshold business operating point"],
                    "trigger": {
                        "field": "learning_goal",
                        "value": profile.learning_goal,
                    },
                }
            ]
        },
        profile,
        neutral_learning_goal="理解评估曲线",
    )

    assert error is None


def test_prediction_profile_validation_rejects_absent_weak_trigger():
    profile = controlled_profiles(_load_tasks()[0])[0]
    error = _validate_prediction_for_profile(
        {
            "obligations": [
                {
                    "kind": "prerequisite",
                    "concept": "初始化",
                    "claim": "补充初始化",
                    "search_terms": ["initialization"],
                    "trigger": {"field": "weak_concept", "value": "初始化"},
                }
            ]
        },
        profile,
    )

    assert error is not None


def test_prediction_schema_rejects_non_english_search_terms():
    error = _validate_prediction(
        {
            "obligations": [
                {
                    "kind": "prerequisite",
                    "concept": "初始化",
                    "claim": "补充初始化",
                    "search_terms": ["初始化"],
                    "trigger": {"field": "weak_concept", "value": "初始化"},
                }
            ]
        }
    )

    assert error is not None


def test_billing_and_auth_failures_are_not_retried():
    assert _is_retryable_status(401) is False
    assert _is_retryable_status(402) is False
    assert _is_retryable_status(403) is False
    assert _is_retryable_status(429) is True


def test_rate_limit_backoff_is_longer_than_generic_retry():
    assert _retry_delay(None, 1) == 2.0
    assert _retry_delay(None, 3) == 8.0
