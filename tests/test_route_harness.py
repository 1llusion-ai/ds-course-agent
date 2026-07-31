"""Tests for the typed, offline route-boundary harness."""

from __future__ import annotations

import json
from types import SimpleNamespace

from benchmarks.route_harness import (
    DEFAULT_CASE_PATH,
    build_route_report,
    evaluate_case,
    load_route_cases,
)
from ds_course_agent.rag.query_pipeline import (
    ExecutionMode,
    RetrievalPolicy,
    RouteDecision,
    RouteFamily,
    RouteIntent,
)


class _FakeService:
    def __init__(self, decision: RouteDecision):
        self.decision = decision
        self.calls = []

    def _prepare_query_route(self, query, session_id, student_id, web_search=False):
        self.calls.append(
            {
                "query": query,
                "session_id": session_id,
                "student_id": student_id,
                "web_search": web_search,
            }
        )
        return SimpleNamespace(decision=self.decision)


def test_route_harness_flags_unexpected_learning_answer_as_unexpected_rag():
    service = _FakeService(
        RouteDecision(
            family=RouteFamily.LEARNING,
            intent=RouteIntent.CONCEPT_QA,
            execution_mode=ExecutionMode.LEARNING_ANSWER,
            confidence=0.8,
            reasons=["课程相关知识问答"],
            retrieval_policy=RetrievalPolicy.REQUIRED,
        )
    )

    result = evaluate_case(
        service,
        {
            "id": "code_explain",
            "query": "帮我解析这段代码",
            "expected_family": "learning",
            "expected_intent": "code_explanation",
            "expected_execution_mode": "direct_model",
            "expected_retrieval_policy": "optional",
            "expected_allowed_tools": [],
            "disallowed_execution_modes": ["learning_answer"],
        },
        student_id="student",
    )

    assert result["passed"] is False
    assert "expected_intent=code_explanation" in result["failures"]
    assert "expected_execution_mode=direct_model" in result["failures"]
    assert "disallowed_execution_mode=learning_answer" in result["failures"]

    report = build_route_report(
        metadata={"name": "unit"},
        case_path="cases.json",
        output_path="report.json",
        student_id="student",
        started_at="2026-07-29T00:00:00+08:00",
        finished_at="2026-07-29T00:00:01+08:00",
        results=[result],
    )

    assert report["summary"]["failed_cases"] == 1
    assert report["summary"]["unexpected_rag_count"] == 1


def test_route_harness_checks_exact_tool_allowlist_and_web_flag():
    service = _FakeService(
        RouteDecision(
            family=RouteFamily.EXTERNAL_RESEARCH,
            intent=RouteIntent.WEB_RESEARCH,
            execution_mode=ExecutionMode.WEB_PIPELINE,
            confidence=1.0,
            retrieval_policy=RetrievalPolicy.REQUIRED,
        )
    )

    result = evaluate_case(
        service,
        {
            "id": "web",
            "query": "请联网搜索最近的 AI 教学资源",
            "web_search": True,
            "expected_family": "external_research",
            "expected_intent": "web_research",
            "expected_execution_mode": "web_pipeline",
            "expected_retrieval_policy": "required",
            "expected_allowed_tools": [],
        },
        student_id="student",
    )

    assert result["passed"] is True
    assert result["allowed_tools"] == []
    assert service.calls[0]["web_search"] is True


def test_canonical_route_dataset_uses_new_contract_and_required_regressions():
    metadata, cases = load_route_cases(DEFAULT_CASE_PATH)

    assert metadata["version"] == "4.0"
    assert len(cases) >= 119
    assert all("expected_family" in case for case in cases)
    assert all("expected_intent" in case for case in cases)
    assert all("expected_execution_mode" in case for case in cases)
    assert all(isinstance(case["expected_allowed_tools"], list) for case in cases)
    assert not any("expected_route" in case for case in cases)
    assert not any("expected_direct_llm_answer" in case for case in cases)

    case_ids = {case["id"] for case in cases}
    assert {
        "alias_loop_not_oop",
        "alias_oop_concept",
        "broad_task_classification",
        "ambiguous_learning",
        "not_learning",
        "generic_code_001",
        "code_review_001",
        "python_exec_001",
    } <= case_ids


def test_route_boundary_audit_tracks_canonical_contract():
    with open("benchmarks/data/route_boundary_v2_audit.json", encoding="utf-8") as file:
        audit = json.load(file)

    assert audit["schema_version"] == 2
    assert audit["summary"]["source_cases"] == "benchmarks/data/route_boundary.json"
    assert audit["summary"]["total_cases"] >= 119
    assert audit["summary"]["accepted_cases"] == audit["summary"]["total_cases"]
    assert audit["summary"]["unexpected_rag_count"] == 0
