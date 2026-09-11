"""Tests for retrieval experiment aggregation."""

from __future__ import annotations

from benchmarks.retrieval_evidence_metrics import aggregate_agent_metrics
from benchmarks.retrieval_experiment_schema import AgentQueryMetrics


def _metric(coverage: float, complete: bool) -> AgentQueryMetrics:
    return AgentQueryMetrics.model_validate(
        {
            "annotator_id": "terra-a",
            "candidate_has_complete_evidence": True,
            "retrieval": {
                "depths": {
                    "1": {
                        "evidence_coverage": coverage,
                        "region_recall": coverage,
                        "complete_evidence": complete,
                        "sufficient_hit": complete,
                    }
                },
                "sufficient_mrr": 1.0 if complete else 0.0,
                "completion_rr": 1.0 if complete else 0.0,
            },
        }
    )


def test_aggregate_keeps_rates_and_coverage_separate() -> None:
    result = aggregate_agent_metrics("terra-a", [_metric(1.0, True), _metric(0.5, False)], [1])
    assert result.depths["1"].evidence_coverage == 0.75
    assert result.depths["1"].complete_evidence_rate == 0.5
    assert result.sufficient_mrr == 0.5
