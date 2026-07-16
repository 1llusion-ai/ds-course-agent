from benchmarks.route_harness import build_route_report, evaluate_case
from ds_course_agent.rag.query_pipeline import RouteDecision, RouteType


class _FakeService:
    def __init__(self, decision):
        self.decision = decision

    def _prepare_query_route(self, query, session_id, student_id):
        return {"decision": self.decision}


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
