"""Deterministic analysis for the knowledge-state search prompt probe."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


def _normalize(text: str) -> str:
    """Normalize text for conservative concept-term matching."""

    return re.sub(r"\s+", "", str(text or "").lower())


def _action_text(result: dict[str, Any]) -> str:
    response = result.get("response") or {}
    actions = response.get("actions") if isinstance(response, dict) else []
    if not isinstance(actions, list):
        return ""
    queries: list[str] = []
    for action in actions:
        if isinstance(action, dict):
            queries.append(str(action.get("query", "")))
    return _normalize(" ".join(queries))


def _coverage(result: dict[str, Any], *, kind: str) -> float | None:
    gap = result.get("evaluation_gap") or result.get("gap") or {}
    requirements = gap.get("core_requirements", []) if kind == "core" else gap.get("learner_requirements", [])
    if not requirements:
        return None
    text = _action_text(result)
    covered = 0
    for requirement in requirements:
        terms = [
            _normalize(requirement.get("concept", "")),
            *(_normalize(t) for t in requirement.get("search_terms", [])),
        ]
        if any(term and term in text for term in terms):
            covered += 1
    return covered / len(requirements)


def analyze(payload: dict[str, Any]) -> dict[str, Any]:
    """Aggregate validity, evidence alignment, and paired trajectory differences."""

    results = payload.get("results", [])
    by_variant: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        by_variant[str(result.get("variant", "unknown"))].append(result)

    summary: dict[str, Any] = {"variants": {}, "paired_profile_differences": []}
    for variant, items in sorted(by_variant.items()):
        successful = [item for item in items if item.get("error") is None and item.get("response") is not None]
        summary["variants"][variant] = {
            "total": len(items),
            "successful": len(successful),
            "success_rate": len(successful) / len(items) if items else 0.0,
            "core_coverage_mean": _mean_coverage(successful, kind="core"),
            "learner_coverage_mean": _mean_coverage(successful, kind="learner"),
            "core_coverage_applicable": sum(_coverage(item, kind="core") is not None for item in successful),
            "learner_coverage_applicable": sum(_coverage(item, kind="learner") is not None for item in successful),
            "avg_action_count": _mean_action_count(successful),
            "shared_search_trajectory": variant in {"generic", "profile_at_answer"},
        }

    grouped: dict[str, dict[str, dict[str, dict[str, Any]]]] = defaultdict(lambda: defaultdict(dict))
    for result in results:
        task_id = str(result.get("task_id"))
        variant = str(result.get("variant"))
        student_id = str(result.get("student_id"))
        grouped[task_id][variant][student_id] = result

    for task_id, variants in sorted(grouped.items()):
        for variant, profile_results in sorted(variants.items()):
            ids = sorted(profile_results)
            for left, right in zip(ids, ids[1:], strict=False):
                left_text = _action_text(profile_results[left])
                right_text = _action_text(profile_results[right])
                summary["paired_profile_differences"].append(
                    {
                        "task_id": task_id,
                        "left_student_id": left,
                        "right_student_id": right,
                        "variant": variant,
                        "different": left_text != right_text,
                        "token_jaccard_distance": _jaccard_distance(left_text, right_text),
                    }
                )
    return summary


def _mean_action_count(items: list[dict[str, Any]]) -> float:
    counts = []
    for item in items:
        response = item.get("response") or {}
        actions = response.get("actions", []) if isinstance(response, dict) else []
        counts.append(len(actions) if isinstance(actions, list) else 0)
    return sum(counts) / len(counts) if counts else 0.0


def _mean_coverage(items: list[dict[str, Any]], *, kind: str) -> float | None:
    values = [_coverage(item, kind=kind) for item in items]
    applicable = [value for value in values if value is not None]
    return sum(applicable) / len(applicable) if applicable else None


def _jaccard_distance(left: str, right: str) -> float:
    left_tokens = set(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", left))
    right_tokens = set(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", right))
    union = left_tokens | right_tokens
    return 0.0 if not union else 1.0 - len(left_tokens & right_tokens) / len(union)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line interface."""

    parser = argparse.ArgumentParser(description="Analyze a knowledge-state search probe artifact.")
    parser.add_argument("input")
    parser.add_argument("--output", default=None)
    return parser


def main() -> int:
    """Load, analyze, print, and optionally persist a summary."""

    args = build_parser().parse_args()
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    summary = analyze(payload)
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
