"""Deterministic checks for personalized closed-loop evaluation traces."""

from __future__ import annotations

from collections import Counter
from typing import Any

from benchmarks.personalized_closed_loop_schema import Dataset, ExpectedChat, Step, Trajectory


def _result(name: str, passed: bool, evidence: str) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def _step_trace(trace: dict[str, Any], step_index: int) -> dict[str, Any]:
    steps = trace.get("steps", [])
    return steps[step_index] if 0 <= step_index < len(steps) and isinstance(steps[step_index], dict) else {}


def score_step(step: Step, observed: dict[str, Any]) -> list[dict[str, Any]]:
    """Score one step using only explicit facts captured by the runner."""

    checks: list[dict[str, Any]] = []
    if step.type == "chat":
        expected: ExpectedChat = step.expected or ExpectedChat()
        if expected.primary_kc_id:
            actual = observed.get("primary_kc_id")
            checks.append(
                _result(
                    "kc_correct",
                    actual == expected.primary_kc_id,
                    f"expected={expected.primary_kc_id!r}, actual={actual!r}",
                )
            )
        if expected.allowed_kc_ids:
            actual_ids = set(observed.get("matched_kc_ids") or [])
            checks.append(
                _result(
                    "kc_allowlist",
                    actual_ids <= set(expected.allowed_kc_ids),
                    f"allowed={expected.allowed_kc_ids!r}, actual={sorted(actual_ids)!r}",
                )
            )
        if expected.personalized_route is not None:
            actual = bool(observed.get("personalized_route"))
            checks.append(
                _result(
                    "personalized_route",
                    actual == expected.personalized_route,
                    f"expected={expected.personalized_route}, actual={actual}",
                )
            )
        checks.append(
            _result(
                "sse_completed", observed.get("terminal_type") == "final", f"terminal={observed.get('terminal_type')!r}"
            )
        )
        checks.append(
            _result("route_recorded", bool(observed.get("intent") or observed.get("family")), "route identity captured")
        )
    elif step.type == "submit_assessment":
        expected = step.outcome
        checks.append(
            _result(
                "answer_outcome_matches",
                observed.get("outcome") == expected,
                f"expected={expected!r}, actual={observed.get('outcome')!r}",
            )
        )
    elif step.type == "retry_last_action":
        before = observed.get("before_counts") or {}
        after = observed.get("after_counts") or {}
        checks.append(_result("idempotent_persistence", before == after, f"before={before!r}, after={after!r}"))
    return checks


def score_trajectory(trajectory: Trajectory, trace: dict[str, Any]) -> dict[str, Any]:
    """Produce deterministic checkpoint results and hard-gate status."""

    observed_steps = trace.get("steps") if isinstance(trace.get("steps"), list) else []
    checks: list[dict[str, Any]] = []
    for index, step in enumerate(trajectory.steps):
        observed = (
            observed_steps[index] if index < len(observed_steps) and isinstance(observed_steps[index], dict) else {}
        )
        checks.extend(score_step(step, observed))
        if step.type == "checkpoint":
            for name in step.checks:
                checks.append(_result(name, bool(observed.get(name)), f"observed={observed.get(name)!r}"))
    by_name = {item["name"]: item for item in checks}
    hard_gates = {gate: bool(by_name.get(gate, {}).get("passed", False)) for gate in trajectory.hard_gates}
    return {
        "trajectory_id": trajectory.id,
        "checks": checks,
        "hard_gates": hard_gates,
        "passed": all(item["passed"] for item in checks) if checks else False,
        "infrastructure_failed": bool(trace.get("infrastructure_error")),
    }


def summarize_scores(dataset: Dataset, results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate scores without discarding per-trajectory evidence."""

    categories = {item.id: item.category for item in dataset.trajectories}
    hard_gate_names = ("kc_correct", "profile_faithful", "student_isolation")
    summary: dict[str, Any] = {
        "trajectory_total": len(dataset.trajectories),
        "trajectory_completed": sum(not item.get("infrastructure_failed") for item in results),
        "infrastructure_failures": sum(bool(item.get("infrastructure_failed")) for item in results),
        "hard_gates": {},
        "functional_checks": {},
        "category_failures": Counter(),
        "failed_trajectory_ids": [item["trajectory_id"] for item in results if not item.get("passed")],
    }
    for gate in hard_gate_names:
        values = [item.get("hard_gates", {}).get(gate) for item in results if gate in item.get("hard_gates", {})]
        summary["hard_gates"][gate] = {
            "pass": sum(value is True for value in values),
            "fail": sum(value is False for value in values),
            "review": sum(value is None for value in values),
        }
    for result in results:
        if not result.get("passed"):
            summary["category_failures"][categories.get(result["trajectory_id"], "unknown")] += 1
        for check in result.get("checks", []):
            bucket = summary["functional_checks"].setdefault(check["name"], {"pass": 0, "fail": 0})
            bucket["pass" if check["passed"] else "fail"] += 1
    summary["category_failures"] = dict(summary["category_failures"])
    return summary


__all__ = ["score_step", "score_trajectory", "summarize_scores"]
