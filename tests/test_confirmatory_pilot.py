"""Tests for the v3 Phase A pilot and deterministic discriminability gate."""

from __future__ import annotations

from dataclasses import replace

from benchmarks.knowledge_state_search.confirmatory_evaluator_v3 import (
    build_annotation_map,
    source_selection_metrics,
)
from benchmarks.knowledge_state_search.confirmatory_matrix_support import (
    adapt_task,
    build_residual_plan,
    summarize_results,
)
from benchmarks.knowledge_state_search.confirmatory_matrix_v3 import run_v3_matrix
from benchmarks.knowledge_state_search.confirmatory_oracle_v3 import (
    V3LexicalRetriever,
    run_discriminability_gate,
)
from benchmarks.knowledge_state_search.confirmatory_pilot import load_confirmatory_pilot
from benchmarks.knowledge_state_search.models import EvidenceGap, EvidenceRequirement


def test_confirmatory_pilot_has_three_typed_gap_tasks():
    schema = load_confirmatory_pilot()

    assert len(schema.tasks) == 3
    assert len(schema.profiles) == 6
    assert len(schema.sources) == 30
    assert len(schema.annotations) == 270
    schema.validate_pilot_contract()


def test_confirmatory_pilot_gate_requires_node_edge_and_path_gain():
    report = run_discriminability_gate(
        schema=load_confirmatory_pilot(),
        top_k=3,
        source_budget=6,
    )

    assert report["summary"]["gate"]["passed"] is True
    assert report["summary"]["learner_gain_task_rate"] == 1.0
    assert report["summary"]["edge_gain_task_rate"] >= 2 / 3
    assert report["summary"]["path_gain_task_rate"] >= 2 / 3
    assert all(item["new_supported_learner_source_ids"] for item in report["results"] if item["learner_claim_ids"])


def test_confirmatory_pilot_is_fingerprinted():
    schema = load_confirmatory_pilot()

    assert schema.manifest.fingerprints
    assert schema.manifest.counts.annotations == 270


def test_v3_planner_adapter_exposes_only_core_claim_ids():
    schema = load_confirmatory_pilot()
    task = schema.tasks[0]
    claims = schema.claims_for_task(task.task_id)
    adapter = adapt_task(task.task_id, task.question, task.target_concepts, claims)
    learner_ids = {claim.claim_id for claim in claims if not claim.hard}

    assert {item.requirement_id for item in adapter.evidence_requirements}.isdisjoint(learner_ids)
    assert {item.requirement_id for item in adapter.evidence_requirements} == {
        claim.claim_id for claim in claims if claim.hard
    }


def test_v3_retrieval_is_invariant_to_annotations_and_provider_labels():
    schema = load_confirmatory_pilot()
    baseline = V3LexicalRetriever(schema).search(
        task_id="gd_learning_rate",
        query="gradient descent learning rate stability",
        top_k=5,
    )
    mutated = replace(
        schema,
        annotations=tuple(reversed(schema.annotations)),
        sources=tuple(replace(source, provider="relation-label-must-not-matter") for source in schema.sources),
    )

    assert (
        V3LexicalRetriever(mutated).search(
            task_id="gd_learning_rate",
            query="gradient descent learning rate stability",
            top_k=5,
        )
        == baseline
    )


def test_null_structured_plan_is_shared_across_profiles(monkeypatch):
    calls = []

    def fake_request(**kwargs):
        calls.append(kwargs["profile"].student_id)
        return {
            "response": {
                "actions": [
                    {
                        "type": "SEARCH",
                        "query": "gradient descent learning rate",
                        "purpose": "cover core evidence",
                        "target_requirements": [],
                    }
                ],
                "stop_reason": "test",
            },
            "error": None,
        }

    monkeypatch.setattr(
        "benchmarks.knowledge_state_search.confirmatory_matrix_v3._request",
        fake_request,
    )
    report = run_v3_matrix(
        api_key="test",
        base_url="http://unused",
        model="test",
        schema=load_confirmatory_pilot(),
        methods=("M1N",),
        limit_tasks=1,
    )

    results = report["results"]
    assert calls == ["gd_learning_rate_null_structured"]
    assert len(results) == 2
    assert results[0]["selected_source_ids"] == results[1]["selected_source_ids"]
    assert results[0]["shared_plan"] is True
    assert results[1]["shared_plan"] is True
    assert sum(item["cost"]["planner_calls"] for item in results) == 0
    assert sum(item["cost"]["shared_planner_call_allocation"] for item in results) == 1
    assert {
        "complete_path_recall_at_2",
        "complete_path_recall_at_3",
        "graph_completion_rate",
        "partial_only_claim_rate",
        "unassigned_source_rate",
    }.issubset(results[0]["metrics"])
    assert report["executed_model_calls"] == 1


def test_v3_unrelated_source_is_reported_as_unassigned():
    schema = load_confirmatory_pilot()
    task_id = "gd_learning_rate"
    claim_ids = tuple(claim.claim_id for claim in schema.core_claims(task_id))

    metrics = source_selection_metrics(
        schema,
        task_id=task_id,
        evaluation_claim_ids=claim_ids,
        selected_source_ids=("gd_unrelated_pr",),
        annotations=build_annotation_map(schema),
    )

    assert metrics["unassigned_source_rate"] == 1.0
    assert metrics["strict_evidence_precision"] == 0.0


def test_m3r_allocates_shared_core_plan_cost(monkeypatch):
    def fake_predict(**kwargs):
        return {
            "prediction": {"obligations": []},
            "raw_prediction": "{}",
            "telemetry": {
                "attempts": 1,
                "latency_seconds": 1.0,
                "prompt_tokens": 10,
                "completion_tokens": 2,
                "total_tokens": 12,
            },
            "error": None,
        }

    def fake_request(**kwargs):
        return {
            "response": {
                "actions": [
                    {
                        "type": "SEARCH",
                        "query": "gradient descent learning rate",
                        "purpose": "cover core evidence",
                        "target_requirements": [],
                    }
                ]
            },
            "telemetry": {
                "attempts": 1,
                "latency_seconds": 2.0,
                "prompt_tokens": 20,
                "completion_tokens": 4,
                "total_tokens": 24,
            },
            "error": None,
        }

    monkeypatch.setattr(
        "benchmarks.knowledge_state_search.confirmatory_matrix_v3.predict_obligations",
        fake_predict,
    )
    monkeypatch.setattr(
        "benchmarks.knowledge_state_search.confirmatory_matrix_v3._request",
        fake_request,
    )

    report = run_v3_matrix(
        api_key="test",
        base_url="http://unused",
        model="test",
        schema=load_confirmatory_pilot(),
        methods=("M3R",),
        limit_tasks=1,
    )

    assert sum(item["cost"]["shared_planner_call_allocation"] for item in report["results"]) == 1
    assert all(item["cost"]["logical_model_calls"] == 1.5 for item in report["results"])
    assert all(item["cost"]["total_tokens"] == 24 for item in report["results"])
    assert report["executed_model_calls"] == 3


def test_residual_plan_preserves_core_anchors_and_adds_one_learner_query():
    gap = EvidenceGap(
        learner_requirements=(
            EvidenceRequirement(
                requirement_id="residual_01",
                kind="prerequisite",
                concept="derivative",
                description="derivative slope",
                search_terms=("derivative as slope", "rate of change"),
            ),
        )
    )
    plan = build_residual_plan(
        {
            "actions": [
                {"type": "SEARCH", "query": "core one"},
                {"type": "SEARCH", "query": "core two"},
                {"type": "SEARCH", "query": "core three"},
            ]
        },
        gap,
    )

    assert [action["query"] for action in plan["actions"]] == [
        "core one",
        "core two",
        "derivative as slope rate of change",
    ]
    assert plan["actions"][-1]["target_requirements"] == ["residual_01"]


def test_unconstrained_predicted_gap_ablation_relaxes_target_contract(monkeypatch):
    planner_contracts = []

    def fake_predict(**kwargs):
        return {
            "prediction": {
                "obligations": [
                    {
                        "kind": "prerequisite",
                        "concept": "derivative",
                        "claim": "derivative slope",
                        "search_terms": ["derivative slope"],
                        "trigger": {"field": "weak_concept", "value": "derivative"},
                    }
                ]
            },
            "raw_prediction": "{}",
            "error": None,
        }

    def fake_request(**kwargs):
        planner_contracts.append(kwargs["enforce_target_contract"])
        return {
            "response": {
                "actions": [
                    {
                        "type": "SEARCH",
                        "query": "gradient descent derivative slope",
                        "purpose": "test",
                        "target_requirements": [],
                    }
                ]
            },
            "error": None,
        }

    monkeypatch.setattr(
        "benchmarks.knowledge_state_search.confirmatory_matrix_v3.predict_obligations",
        fake_predict,
    )
    monkeypatch.setattr(
        "benchmarks.knowledge_state_search.confirmatory_matrix_v3._request",
        fake_request,
    )

    report = run_v3_matrix(
        api_key="test",
        base_url="http://unused",
        model="test",
        schema=load_confirmatory_pilot(),
        methods=("M2U",),
        limit_tasks=1,
    )

    assert len(report["results"]) == 2
    assert planner_contracts == [False, False]
    assert report["executed_model_calls"] == 4


def test_summary_reports_failure_adjusted_metrics():
    base = {
        "method": "M3",
        "visible_gap": {"learner_requirements": [{"requirement_id": "learner"}]},
        "search_calls": 1,
        "retrieval_source_count": 1,
        "cost": {
            "logical_model_calls": 2,
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
            "latency_seconds": None,
        },
    }
    metrics = {
        "core_recall": 1.0,
        "learner_recall": 1.0,
        "edge_recall": 1.0,
        "path_recall": 1.0,
        "complete_path_recall_at_2": 1.0,
        "complete_path_recall_at_3": 1.0,
        "graph_completion_rate": 1.0,
        "partial_only_claim_rate": 0.0,
        "claim_conflict_rate": 0.0,
        "strict_evidence_precision": 1.0,
        "graded_evidence_precision": 1.0,
        "contradiction_source_rate": 0.0,
        "distractor_source_rate": 0.0,
        "unassigned_source_rate": 0.0,
    }

    summary = summarize_results(
        [
            {**base, "error": None, "metrics": metrics},
            {**base, "error": "schema_invalid", "metrics": metrics},
        ]
    )["M3"]

    assert summary["successful"] == 1
    assert summary["failed"] == 1
    assert summary["success_rate"] == 0.5
    assert summary["core_recall_mean"] == 1.0
    assert summary["core_recall_failure_adjusted_mean"] == 0.5
    assert summary["learner_recall_failure_adjusted_mean"] == 0.5
    assert summary["coverage_failure_adjusted_mean"] == 0.5
