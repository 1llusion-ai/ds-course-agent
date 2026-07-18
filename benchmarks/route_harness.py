"""Route-boundary harness for the teaching agent.

This harness checks QueryPipeline/AgentService route decisions without executing
LLM calls or RAG retrieval.  It complements latency_harness: latency can be good
while the wrong route is chosen, so route correctness must be measured directly.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_CASE_PATH = Path(__file__).parent / "data" / "route_boundary_v1.json"
DEFAULT_REPORT_PATH = Path("var") / "artifacts" / "benchmarks" / "route_harness_report.json"
DEFAULT_STUDENT_ID = "route_harness_student"


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_route_cases(
    path: Path | str = DEFAULT_CASE_PATH, limit: int | None = None
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    metadata = {key: value for key, value in payload.items() if key != "cases"}
    cases = payload.get("cases") or []
    if not isinstance(cases, list):
        raise ValueError(f"Expected 'cases' list in route harness file: {path}")
    if limit is not None:
        cases = cases[:limit]
    return metadata, [case for case in cases if isinstance(case, dict)]


def evaluate_case(service: Any, case: dict[str, Any], *, student_id: str) -> dict[str, Any]:
    session_id = f"route_harness_{case.get('id') or 'case'}"
    error = None
    route = "unknown"
    retrieval_policy = "unknown"
    confidence = None
    reasons: list[str] = []

    try:
        state = service._prepare_query_route(str(case.get("query") or ""), session_id, student_id)
        decision = state["decision"]
        route = getattr(decision.route, "value", str(decision.route))
        retrieval_policy = decision.retrieval_policy
        confidence = decision.confidence
        reasons = list(decision.reasons or [])
    except Exception as exc:  # pragma: no cover - surfaced in JSON report
        error = {"type": type(exc).__name__, "message": str(exc)}

    expected_route = case.get("expected_route")
    expected_policy = case.get("expected_retrieval_policy")
    disallowed_routes = set(case.get("disallowed_routes") or [])
    failures = []
    if error:
        failures.append("route_exception")
    if expected_route and route != expected_route:
        failures.append(f"expected_route={expected_route}")
    if expected_policy and retrieval_policy != expected_policy:
        failures.append(f"expected_retrieval_policy={expected_policy}")
    if route in disallowed_routes:
        failures.append(f"disallowed_route={route}")

    return {
        "id": case.get("id"),
        "query": case.get("query"),
        "expected_route": expected_route,
        "expected_retrieval_policy": expected_policy,
        "disallowed_routes": sorted(disallowed_routes),
        "route": route,
        "retrieval_policy": retrieval_policy,
        "confidence": confidence,
        "reasons": reasons,
        "passed": not failures,
        "failures": failures,
        "error": error,
    }


def build_route_report(
    *,
    metadata: dict[str, Any],
    case_path: Path | str,
    output_path: Path | str,
    student_id: str,
    started_at: str,
    finished_at: str,
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for item in results if item.get("passed"))
    unexpected_rag = sum(
        1
        for item in results
        if item.get("route") == "grounded_rag" and "grounded_rag" in set(item.get("disallowed_routes") or [])
    )
    return {
        "metadata": {
            "harness_name": "route_harness",
            "version": "0.1",
            "generated_at": finished_at,
            "started_at": started_at,
            "finished_at": finished_at,
            "case_path": str(case_path),
            "output_path": str(output_path),
            "student_id": student_id,
            **metadata,
        },
        "summary": {
            "total_cases": total,
            "passed_cases": passed,
            "failed_cases": total - passed,
            "route_correct_rate": passed / total if total else 0.0,
            "unexpected_rag_count": unexpected_rag,
        },
        "results": results,
    }


def run_route_harness(
    *,
    case_path: Path | str = DEFAULT_CASE_PATH,
    output_path: Path | str = DEFAULT_REPORT_PATH,
    limit: int | None = None,
    student_id: str = DEFAULT_STUDENT_ID,
) -> dict[str, Any]:
    started_at = _now_iso()
    metadata, cases = load_route_cases(case_path, limit=limit)

    from ds_course_agent.rag.agent import AgentService

    service = AgentService()
    results = [evaluate_case(service, case, student_id=student_id) for case in cases]
    finished_at = _now_iso()
    report = build_route_report(
        metadata=metadata,
        case_path=case_path,
        output_path=output_path,
        student_id=student_id,
        started_at=started_at,
        finished_at=finished_at,
        results=results,
    )

    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Route harness: {report['summary']['passed_cases']}/{report['summary']['total_cases']} passed")
    print(f"Unexpected RAG: {report['summary']['unexpected_rag_count']}")
    for item in results:
        status = "OK" if item["passed"] else "FAIL"
        print(f"[{status}] {item['id']}: route={item['route']} policy={item['retrieval_policy']}")
        if item["failures"]:
            print(f"       failures={item['failures']}")
    print(f"Saved report to: {output_file}")
    return report


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run route-boundary checks without executing LLM/RAG")
    parser.add_argument("--cases", default=str(DEFAULT_CASE_PATH), help="Path to route boundary case JSON")
    parser.add_argument("--output", default=str(DEFAULT_REPORT_PATH), help="Where to save JSON report")
    parser.add_argument("--limit", type=int, default=None, help="Only run first N cases")
    parser.add_argument("--student-id", default=DEFAULT_STUDENT_ID, help="Student id used in route preparation")
    return parser


if __name__ == "__main__":
    args = build_arg_parser().parse_args()
    run_route_harness(
        case_path=args.cases,
        output_path=args.output,
        limit=args.limit,
        student_id=args.student_id,
    )
