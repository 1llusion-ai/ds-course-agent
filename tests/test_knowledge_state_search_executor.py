"""Tests for the real-search evidence executor."""

from __future__ import annotations

from benchmarks.knowledge_state_search.execute_probe import _match_requirements, _query_actions, summarize


def test_query_actions_only_returns_searchable_actions():
    result = {
        "response": {
            "actions": [
                {"type": "SEARCH", "query": "K-means 局部最优"},
                {"type": "FETCH", "query": "https://example.com"},
                {"type": "FINISH", "query": ""},
                {"type": "REFINE", "query": "K-means 初始化"},
            ]
        }
    }

    assert _query_actions(result) == ["K-means 局部最优", "K-means 初始化"]


def test_match_requirements_uses_curated_terms():
    result = {
        "gap": {
            "core_requirements": [
                {"requirement_id": "core", "concept": "局部最优", "search_terms": ["局部最优"]},
            ],
            "learner_requirements": [
                {"requirement_id": "learner", "concept": "初始化", "search_terms": ["初始化"]},
            ],
        }
    }

    assert _match_requirements("K-means 会落入局部最优，并且依赖初始化", result, kind="core")["covered"] == 1.0
    assert _match_requirements("K-means 会落入局部最优，并且依赖初始化", result, kind="learner")["covered"] == 1.0


def test_empty_learner_gap_is_not_counted_as_perfect_coverage():
    result = {"gap": {"core_requirements": [], "learner_requirements": []}}

    coverage = _match_requirements("任意文本", result, kind="learner")

    assert coverage["applicable"] is False
    assert coverage["covered"] is None


def test_summarize_aggregates_search_cost():
    executions = [
        {
            "variant": "gap_planner",
            "core_evidence_coverage": {"covered": 1.0},
            "learner_evidence_coverage": {"covered": 0.5},
            "search_calls": 2,
            "successful_searches": 2,
            "fetch_calls": 4,
            "successful_fetches": 3,
            "unique_sources": 3,
            "elapsed_seconds": 1.0,
        }
    ]

    summary = summarize(executions)

    assert summary["variants"]["gap_planner"]["core_coverage_mean"] == 1.0
    assert summary["variants"]["gap_planner"]["search_calls"] == 2
    assert summary["variants"]["gap_planner"]["successful_fetches"] == 3
