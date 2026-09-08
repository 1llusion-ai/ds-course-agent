"""Offline route-boundary harness for the teaching agent.

The harness exercises ``QueryPipeline.prepare`` and the production router, but
stubs concept/profile enrichment and semantic-router outputs so it never calls
an LLM, embedding service, RAG retriever, or executable tool.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_CASE_PATH = Path(__file__).parent / "data" / "route_boundary.json"
DEFAULT_REPORT_PATH = Path("var") / "artifacts" / "benchmarks" / "route_harness_report.json"
DEFAULT_STUDENT_ID = "route_harness_student"


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_route_cases(
    path: Path | str = DEFAULT_CASE_PATH,
    limit: int | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Load and minimally validate canonical route cases."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    metadata = {key: value for key, value in payload.items() if key != "cases"}
    cases = payload.get("cases") or []
    if not isinstance(cases, list):
        raise ValueError(f"Expected 'cases' list in route harness file: {path}")

    required = {
        "id",
        "query",
        "expected_family",
        "expected_intent",
        "expected_execution_mode",
        "expected_allowed_tools",
    }
    normalized_cases = [case for case in cases if isinstance(case, dict)]
    for index, case in enumerate(normalized_cases):
        missing = sorted(required - case.keys())
        if missing:
            raise ValueError(f"Route case #{index} ({case.get('id')!r}) is missing fields: {missing}")
        if not isinstance(case["expected_allowed_tools"], list):
            raise ValueError(f"Route case {case['id']!r} expected_allowed_tools must be a list")

    if limit is not None:
        normalized_cases = normalized_cases[:limit]
    return metadata, normalized_cases


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def evaluate_case(service: Any, case: dict[str, Any], *, student_id: str) -> dict[str, Any]:
    """Evaluate one case against the typed routing contract."""

    session_id = f"route_harness_{case.get('id') or 'case'}"
    error = None
    family = "unknown"
    intent = "unknown"
    execution_mode = "unknown"
    retrieval_policy = "unknown"
    allowed_tools: list[str] = []
    confidence = None
    reasons: list[str] = []

    configure_semantic = getattr(service, "configure_semantic_output", None)
    if callable(configure_semantic):
        configure_semantic(case.get("semantic_router_output"))

    try:
        state = service._prepare_query_route(
            str(case.get("query") or ""),
            session_id,
            student_id,
            web_search=bool(case.get("web_search", False)),
        )
        decision = state.decision
        family = _enum_value(decision.family)
        intent = _enum_value(decision.intent)
        execution_mode = _enum_value(decision.execution_mode)
        retrieval_policy = _enum_value(decision.retrieval_policy)
        allowed_tools = list(decision.allowed_tools)
        confidence = decision.confidence
        reasons = list(decision.reasons or [])
    except Exception as exc:  # pragma: no cover - surfaced in JSON report
        error = {"type": type(exc).__name__, "message": str(exc)}

    expected_family = case.get("expected_family")
    expected_intent = case.get("expected_intent")
    expected_execution_mode = case.get("expected_execution_mode")
    expected_policy = case.get("expected_retrieval_policy")
    expected_allowed_tools = list(case.get("expected_allowed_tools") or [])
    disallowed_modes = set(case.get("disallowed_execution_modes") or [])

    failures = []
    if error:
        failures.append("route_exception")
    if expected_family and family != expected_family:
        failures.append(f"expected_family={expected_family}")
    if expected_intent and intent != expected_intent:
        failures.append(f"expected_intent={expected_intent}")
    if expected_execution_mode and execution_mode != expected_execution_mode:
        failures.append(f"expected_execution_mode={expected_execution_mode}")
    if expected_policy and retrieval_policy != expected_policy:
        failures.append(f"expected_retrieval_policy={expected_policy}")
    if allowed_tools != expected_allowed_tools:
        failures.append(f"expected_allowed_tools={expected_allowed_tools}")
    if execution_mode in disallowed_modes:
        failures.append(f"disallowed_execution_mode={execution_mode}")

    return {
        "id": case.get("id"),
        "category": case.get("category"),
        "query": case.get("query"),
        "web_search": bool(case.get("web_search", False)),
        "semantic_router_output": case.get("semantic_router_output"),
        "expected_family": expected_family,
        "expected_intent": expected_intent,
        "expected_execution_mode": expected_execution_mode,
        "expected_retrieval_policy": expected_policy,
        "expected_allowed_tools": expected_allowed_tools,
        "disallowed_execution_modes": sorted(disallowed_modes),
        "family": family,
        "intent": intent,
        "execution_mode": execution_mode,
        "retrieval_policy": retrieval_policy,
        "allowed_tools": allowed_tools,
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
    """Build the stable JSON report consumed by tests and CI."""

    total = len(results)
    passed = sum(1 for item in results if item.get("passed"))
    unexpected_rag = sum(
        1
        for item in results
        if item.get("execution_mode") == "grounded_generation"
        and "grounded_generation" in set(item.get("disallowed_execution_modes") or [])
    )
    return {
        "metadata": {
            "harness_name": "route_harness",
            "version": "1.0",
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
            # Keep the historical metric name while redefining RAG by its
            # execution contract rather than the removed GROUNDED_RAG route.
            "unexpected_rag_count": unexpected_rag,
        },
        "results": results,
    }


@dataclass(frozen=True)
class _SemanticOutput:
    intent: Any
    confidence: float
    needs_clarification: bool


class _HarnessSemanticRouter:
    """Deterministic semantic-router stub configured by each benchmark case."""

    def __init__(self) -> None:
        self._payload: dict[str, Any] | None = None

    def configure(self, payload: dict[str, Any] | None) -> None:
        self._payload = dict(payload) if payload else None

    def route(self, query: str, recent_context: str = "") -> _SemanticOutput:
        del query, recent_context
        from ds_course_agent.agent.routing import RouteIntent

        payload = self._payload or {
            "intent": RouteIntent.NEEDS_CLARIFICATION.value,
            "confidence": 0.0,
            "needs_clarification": True,
        }
        return _SemanticOutput(
            intent=RouteIntent(str(payload["intent"])),
            confidence=float(payload.get("confidence", 1.0)),
            needs_clarification=bool(payload.get("needs_clarification", False)),
        )


class _NoopHooks:
    def before_route(self, state: Any) -> None:
        del state

    def after_route(self, state: Any, decision: Any) -> None:
        del state, decision


class _OfflineRouteService:
    """Minimal QueryPipeline host with no external service dependencies."""

    def __init__(self) -> None:
        import ds_course_agent.agent.routing.router as router_module
        from ds_course_agent.agent.routing.router import QueryRouter

        self._semantic_router = _HarnessSemanticRouter()
        router_module._router = QueryRouter(semantic_router=self._semantic_router)
        self.system_prompt = ""
        self.hooks = _NoopHooks()

    def configure_semantic_output(self, payload: dict[str, Any] | None) -> None:
        self._semantic_router.configure(payload)

    def _prepare_query_route(
        self,
        user_input: str,
        session_id: str,
        student_id: str,
        web_search: bool = False,
    ) -> Any:
        from ds_course_agent.agent.routing import QueryPipeline

        return QueryPipeline(self).prepare(
            user_input,
            session_id,
            student_id,
            web_search=web_search,
        )

    def _warn_context_budget(self, messages: list[Any], *, location: str, **metadata: Any) -> None:
        del messages, location, metadata

    @staticmethod
    def _handle_special_case(question: str) -> str | None:
        from ds_course_agent.agent.taxonomy import special_case_response

        return special_case_response(question)

    def _enrich_skills(self, context: Any, user_input: str) -> set[str]:
        from ds_course_agent.teaching.skill_system import get_skill_loader

        candidates = {match.skill.key for match in get_skill_loader().select_candidates(user_input)}
        context.skill_candidate_keys = candidates
        return candidates

    @staticmethod
    def _map_learning_concepts(context: Any, user_input: str) -> list[Any]:
        del user_input
        context.detected_concepts = []
        return []

    @staticmethod
    def _load_learner_state(context: Any, student_id: str) -> Any:
        from ds_course_agent.teaching.learner_state import LearnerStateSnapshot

        learner_state = LearnerStateSnapshot(student_id=student_id)
        context.learner_state_summary = learner_state.summary()
        return learner_state

    @staticmethod
    def _rewrite_learning_query(context: Any) -> Any:
        from ds_course_agent.agent.routing import get_rewriter

        result = get_rewriter().rewrite(context)
        context.grounded_tool_query = result.enriched_query
        return result

    @staticmethod
    def _record_learning_events(**kwargs: Any) -> None:
        del kwargs

    @staticmethod
    def _build_route_state(**kwargs: Any) -> Any:
        from ds_course_agent.agent.routing import RouteState

        return RouteState(
            context=kwargs["context"],
            decision=kwargs["decision"],
            chat_history=kwargs["chat_history"],
            student_id=kwargs["student_id"],
            session_id=kwargs["session_id"],
            history=kwargs["history"],
            learner_state=kwargs["learner_state"],
            matched_concepts=kwargs["matched_concepts"],
            skill_candidate_keys=kwargs["skill_candidate_keys"],
            special_case_response=kwargs["special_case_response"],
            stream_id=kwargs.get("stream_id"),
        )

    def _get_hooks(self) -> _NoopHooks:
        return self.hooks


def run_route_harness(
    *,
    case_path: Path | str = DEFAULT_CASE_PATH,
    output_path: Path | str = DEFAULT_REPORT_PATH,
    limit: int | None = None,
    student_id: str = DEFAULT_STUDENT_ID,
) -> dict[str, Any]:
    """Run the canonical route suite without model or retrieval dependencies."""

    started_at = _now_iso()
    metadata, cases = load_route_cases(case_path, limit=limit)
    service = _OfflineRouteService()
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
        print(
            f"[{status}] {item['id']}: "
            f"{item['family']}/{item['intent']}/{item['execution_mode']} "
            f"policy={item['retrieval_policy']}"
        )
        if item["failures"]:
            print(f"       failures={item['failures']}")
    print(f"Saved report to: {output_file}")
    return report


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run offline route-boundary contract checks")
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
