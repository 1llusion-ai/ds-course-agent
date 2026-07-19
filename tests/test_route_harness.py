import json
from types import SimpleNamespace

from benchmarks.route_harness import build_route_report, evaluate_case, load_route_cases
from ds_course_agent.rag.query_pipeline import RouteDecision, RouteType


class _FakeService:
    def __init__(self, decision):
        self.decision = decision
        self.calls = []

    def _prepare_query_route(self, query, session_id, student_id, web_search=False):
        # QueryPipeline.prepare returns a typed RouteState; the harness reads
        # state.decision directly (the old dict compat shim was removed).
        self.calls.append(
            {
                "query": query,
                "session_id": session_id,
                "student_id": student_id,
                "web_search": web_search,
            }
        )
        return SimpleNamespace(decision=self.decision)


def test_route_harness_evaluate_case_flags_unexpected_rag():
    service = _FakeService(
        RouteDecision(
            route=RouteType.GROUNDED_RAG,
            confidence=0.8,
            reasons=["课程相关知识问答"],
            retrieval_policy="required",
        )
    )

    result = evaluate_case(
        service,
        {
            "id": "code_explain",
            "query": "帮我解析这段代码",
            "expected_route": "generic_agent",
            "expected_retrieval_policy": "optional",
            "disallowed_routes": ["grounded_rag"],
        },
        student_id="student",
    )

    assert result["passed"] is False
    assert "expected_route=generic_agent" in result["failures"]
    assert "disallowed_route=grounded_rag" in result["failures"]

    report = build_route_report(
        metadata={"name": "unit"},
        case_path="cases.json",
        output_path="report.json",
        student_id="student",
        started_at="2026-07-16T00:00:00+08:00",
        finished_at="2026-07-16T00:00:01+08:00",
        results=[result],
    )

    assert report["summary"]["failed_cases"] == 1
    assert report["summary"]["unexpected_rag_count"] == 1


def test_route_harness_passes_web_search_flag_to_pipeline():
    service = _FakeService(
        RouteDecision(
            route=RouteType.GENERIC_AGENT,
            confidence=1.0,
            reasons=["显式联网搜索"],
            retrieval_policy="optional",
        )
    )

    result = evaluate_case(
        service,
        {
            "id": "web",
            "query": "请联网搜索最近的 AI 新闻",
            "web_search": True,
            "expected_route": "generic_agent",
        },
        student_id="student",
    )

    assert result["passed"] is True
    assert result["web_search"] is True
    assert service.calls[0]["web_search"] is True


def test_route_boundary_v2_dataset_shape():
    metadata, cases = load_route_cases("benchmarks/data/route_boundary_v2.json")

    counts = {}
    for case in cases:
        counts[case["category"]] = counts.get(case["category"], 0) + 1

    assert metadata["version"] == "2.0"
    assert len(cases) == 114
    assert counts["grounded_rag"] == 20
    assert counts["special_direct"] == 12
    assert counts["web_search"] == 6
    assert any(case.get("expected_direct_llm_answer") for case in cases)


def test_route_boundary_v2_audit_metadata():
    with open("benchmarks/data/route_boundary_v2_audit.json", encoding="utf-8") as f:
        audit = json.load(f)

    assert audit["summary"]["total_cases"] == 114
    assert audit["summary"]["accepted_cases"] == 114
    assert audit["summary"]["unexpected_rag_count"] == 0
