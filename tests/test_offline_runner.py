"""Tests for the fixed-snapshot M0-M5 runner contracts."""

from __future__ import annotations

import json
from pathlib import Path

from benchmarks.knowledge_state_search.confirmatory_analysis import analyze_confirmatory
from benchmarks.knowledge_state_search.controlled_profiles import controlled_profiles, wrong_gap
from benchmarks.knowledge_state_search.evidence import EvidenceSnapshot
from benchmarks.knowledge_state_search.gap_planner import KnowledgeStateGapPlanner
from benchmarks.knowledge_state_search.models import SearchTask
from benchmarks.knowledge_state_search.offline_runner import _configured_model, _execute_queries
from benchmarks.knowledge_state_search.selective_gap import (
    ObligationTrigger,
    PredictedObligation,
    neutralize_trigger,
    obligations_to_gap,
    select_counterfactual_obligations,
)
from benchmarks.knowledge_state_search.snapshot_retriever import SnapshotRetriever

DATA_PATH = Path("benchmarks/data/knowledge_state_search_probe_v1.json")


def _load_tasks() -> list[SearchTask]:
    payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    return [SearchTask.from_dict(item) for item in payload["tasks"]]


def test_controlled_pairs_cover_two_prerequisite_one_misconception_one_goal():
    planner = KnowledgeStateGapPlanner()
    observed = []
    for task in _load_tasks():
        _, single_gap = controlled_profiles(task)
        observed.append(planner.plan(task, single_gap).learner_requirements[0].kind)

    assert observed.count("prerequisite") == 2
    assert observed.count("misconception") == 1
    assert observed.count("goal") == 1


def test_trigger_neutralization_removes_weak_concept():
    profile = controlled_profiles(_load_tasks()[0])[1]
    trigger = ObligationTrigger(field="weak_concept", value="初始化")

    neutralized = neutralize_trigger(profile, trigger)

    assert "初始化" not in neutralized.weak_concepts
    assert "初始化" in neutralized.mastered_concepts


def test_selective_gate_drops_obligation_that_survives_counterfactual():
    obligation = PredictedObligation(
        kind="prerequisite",
        concept="初始化",
        claim="补充初始化",
        search_terms=("初始化",),
        trigger=ObligationTrigger(field="weak_concept", value="初始化"),
        priority=1,
    )
    counterfactual = PredictedObligation(
        kind="prerequisite",
        concept="初始化",
        claim="仍然输出同一个 obligation",
        search_terms=("初始化",),
        trigger=ObligationTrigger(field="weak_concept", value="初始化"),
        priority=1,
    )

    selected = select_counterfactual_obligations(
        (obligation,),
        {obligation.trigger: (counterfactual,)},
    )

    assert selected == ()


def test_obligations_to_gap_preserves_core_contract():
    task = _load_tasks()[0]
    obligation = PredictedObligation(
        kind="prerequisite",
        concept="初始化",
        claim="补充初始化",
        search_terms=("初始化",),
        trigger=ObligationTrigger(field="weak_concept", value="初始化"),
        priority=1,
    )

    gap = obligations_to_gap(task, (obligation,), id_prefix="selective")

    assert {item.requirement_id for item in gap.core_requirements} == {
        "core_objective_update",
        "core_local_minimum",
    }
    assert gap.learner_requirements[0].requirement_id == "selective_01"


def test_wrong_gap_is_not_the_controlled_single_gap():
    task = _load_tasks()[0]
    _, single_gap = controlled_profiles(task)
    gold = KnowledgeStateGapPlanner().plan(task, single_gap)
    wrong = wrong_gap(task)

    assert {item.requirement_id for item in wrong.learner_requirements}.isdisjoint(
        item.requirement_id for item in gold.learner_requirements
    )


def test_snapshot_query_execution_returns_only_source_ids():
    snapshot = EvidenceSnapshot.load("benchmarks/data/knowledge_state_search_snapshot_v1")
    retriever = SnapshotRetriever(snapshot)

    source_ids, retrievals = _execute_queries(
        retriever,
        task_id="kmeans_initialization",
        plan={"actions": [{"type": "SEARCH", "query": "KMeans local minima initialization"}]},
        top_k=1,
        max_queries=3,
    )

    assert source_ids
    assert retrievals[0]["hits"][0]["source_id"] in source_ids
    assert "status" not in retrievals[0]["hits"][0]


def test_configured_short_model_name_uses_provider_prefix(monkeypatch):
    monkeypatch.setenv("MIMO_MODEL", "mimo-v2.5-pro")
    monkeypatch.setenv("MIMO_PROVIDER", "xiaomi")
    monkeypatch.delenv("PROFILE_EVAL_MODEL", raising=False)

    assert _configured_model() == "xiaomi/mimo-v2.5-pro"


def test_confirmatory_analysis_reports_paired_metrics():
    payload = {
        "config": {"repeats": 1, "snapshot_id": "fixture-v2"},
        "results": [
            {
                "task_id": "task",
                "student_id": "task_nogap",
                "repeat": 1,
                "method": "M1",
                "error": None,
                "search_calls": 2,
                "selected_source_ids": ["s1"],
                "evaluation_gap": {"learner_requirements": []},
                "metrics": {
                    "hard_core_recall": 0.5,
                    "learner_recall": None,
                    "evidence_precision": 0.5,
                    "strict_supported_rate": 0.5,
                    "contradicted_rate": 0.0,
                    "unannotated_rate": 0.5,
                },
            },
            {
                "task_id": "task",
                "student_id": "task_nogap",
                "repeat": 1,
                "method": "M3",
                "error": None,
                "search_calls": 1,
                "selected_source_ids": ["s1"],
                "evaluation_gap": {"learner_requirements": []},
                "visible_gap": {"learner_requirements": []},
                "metrics": {
                    "hard_core_recall": 1.0,
                    "learner_recall": None,
                    "evidence_precision": 1.0,
                    "strict_supported_rate": 1.0,
                    "contradicted_rate": 0.0,
                    "unannotated_rate": 0.0,
                },
            },
        ],
    }

    report = analyze_confirmatory(payload, source_artifact="fixture.json")

    assert report["paired_m3_vs_m1"]["metrics"]["hard_core_recall"]["mean_delta"] == 0.5
    assert report["paired_m3_vs_m1"]["m3_no_gap_visible_obligation_rate"] == 0.0
