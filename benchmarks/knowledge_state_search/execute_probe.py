"""Execute planner queries against the existing web search/fetch tools."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from benchmarks.knowledge_state_search.gap_planner import KnowledgeStateGapPlanner
from benchmarks.knowledge_state_search.models import SearchTask
from ds_course_agent.tools.web_fetch import fetch_web_pages
from ds_course_agent.tools.web_search import search_web

DEFAULT_TASKS = Path("benchmarks/data/knowledge_state_search_probe_v1.json")
DEFAULT_PLAN = Path("var/artifacts/knowledge_state_search/probe_v1_final.json")
DEFAULT_OUTPUT = Path("var/artifacts/knowledge_state_search/evidence_probe_v1.json")
DEFAULT_VARIANTS = ("generic", "profile_prompt", "gap_planner")


def _load_tasks(path: Path) -> dict[str, SearchTask]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {task.task_id: task for task in (SearchTask.from_dict(item) for item in payload["tasks"])}


def _load_plan(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_env() -> None:
    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)


def _query_actions(result: dict[str, Any]) -> list[str]:
    response = result.get("response") or {}
    actions = response.get("actions", []) if isinstance(response, dict) else []
    queries: list[str] = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        if str(action.get("type", "")).upper() not in {"SEARCH", "REFINE"}:
            continue
        query = str(action.get("query", "")).strip()
        if query and query not in queries:
            queries.append(query)
    return queries


def _select_results(
    payload: dict[str, Any],
    *,
    variants: tuple[str, ...],
    task_ids: set[str] | None,
) -> list[dict[str, Any]]:
    """Deduplicate shared baseline clones before external search execution."""

    selected: list[dict[str, Any]] = []
    seen_shared: set[tuple[str, str]] = set()
    for result in payload.get("results", []):
        task_id = str(result.get("task_id", ""))
        variant = str(result.get("variant", ""))
        if task_ids and task_id not in task_ids:
            continue
        if variant not in variants:
            continue
        if variant in {"generic", "profile_at_answer"}:
            key = (task_id, "generic")
            if key in seen_shared:
                continue
            seen_shared.add(key)
        selected.append(result)
    return sorted(
        selected,
        key=lambda item: (str(item.get("task_id")), str(item.get("variant")), str(item.get("student_id"))),
    )


def _match_requirements(text: str, result: dict[str, Any], *, kind: str) -> dict[str, Any]:
    """Estimate evidence coverage using manually curated requirement terms."""

    normalized = str(text or "").lower().replace(" ", "")
    gap = result.get("gap") or {}
    requirements = gap.get("core_requirements", []) if kind == "core" else gap.get("learner_requirements", [])
    matched: list[str] = []
    missed: list[str] = []
    for requirement in requirements:
        requirement_id = str(requirement.get("requirement_id", ""))
        terms = [str(requirement.get("concept", "")), *map(str, requirement.get("search_terms", []))]
        if any(term.strip() and term.lower().replace(" ", "") in normalized for term in terms):
            matched.append(requirement_id)
        else:
            missed.append(requirement_id)
    return {
        "applicable": bool(requirements),
        "covered": len(matched) / len(requirements) if requirements else None,
        "matched": matched,
        "missed": missed,
    }


def _search_evidence_text(response: Any) -> str:
    """Return source content without query/header text that would leak metrics."""

    parts: list[str] = []
    for item in response.results:
        parts.extend((str(item.title), str(item.snippet)))
    return "\n".join(parts)


def execute_result(
    result: dict[str, Any],
    *,
    top_k: int,
    fetch_top_n: int,
    max_attempts: int,
) -> dict[str, Any]:
    """Run all planned queries for one task/profile/variant."""

    started = time.monotonic()
    queries = _query_actions(result)
    searches: list[dict[str, Any]] = []
    fetched: list[dict[str, Any]] = []
    evidence_parts: list[str] = []
    fetch_calls = 0
    fetch_successes = 0

    for query in queries:
        search_started = time.monotonic()
        response = search_web(query, top_k=top_k)
        search_record = {
            "query": query,
            "provider": response.provider,
            "ok": response.ok,
            "error": response.error,
            "elapsed_seconds": round(time.monotonic() - search_started, 3),
            "results": [item.source_dict(index) for index, item in enumerate(response.results, start=1)],
            "evidence_context": response.evidence_context,
        }
        searches.append(search_record)
        evidence_parts.append(_search_evidence_text(response))

        urls = [item.url for item in response.results if item.url]
        if not urls or fetch_top_n <= 0:
            continue
        pages = fetch_web_pages(
            urls,
            top_n=fetch_top_n,
            max_attempts=max_attempts,
            max_workers=min(4, max_attempts),
        )
        fetch_calls += len(pages)
        for page in pages:
            fetched_record = {
                "url": page.url,
                "final_url": page.final_url,
                "title": page.title,
                "ok": page.ok,
                "extractor": page.extractor,
                "status_code": page.status_code,
                "truncated": page.truncated,
                "error": page.error,
                "text": page.text[:4000],
            }
            fetched.append(fetched_record)
            if page.ok:
                fetch_successes += 1
                evidence_parts.append(page.text)

    evidence_text = "\n".join(evidence_parts)
    core = _match_requirements(evidence_text, result, kind="core")
    learner = _match_requirements(evidence_text, result, kind="learner")
    return {
        "task_id": result.get("task_id"),
        "student_id": result.get("student_id"),
        "variant": result.get("variant"),
        "profile": result.get("profile"),
        "planned_queries": queries,
        "search_calls": len(searches),
        "successful_searches": sum(1 for item in searches if item["ok"]),
        "fetch_calls": fetch_calls,
        "successful_fetches": fetch_successes,
        "unique_sources": len(
            {source.get("url") for item in searches for source in item.get("results", []) if source.get("url")}
        ),
        "core_evidence_coverage": core,
        "learner_evidence_coverage": learner,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "evidence_text": evidence_text[:16000],
        "searches": searches,
        "fetched": fetched,
        "error": None,
    }


def summarize(executions: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate actual search coverage and cost by planner variant."""

    by_variant: dict[str, list[dict[str, Any]]] = {}
    for item in executions:
        by_variant.setdefault(str(item.get("variant")), []).append(item)

    summary: dict[str, Any] = {"variants": {}, "total_executions": len(executions)}
    for variant, items in sorted(by_variant.items()):
        summary["variants"][variant] = {
            "executions": len(items),
            "core_coverage_mean": _mean_nested(items, "core_evidence_coverage", "covered"),
            "learner_coverage_mean": _mean_nested(items, "learner_evidence_coverage", "covered"),
            "search_calls": _sum_unique_cost(items, "search_calls"),
            "successful_searches": _sum_unique_cost(items, "successful_searches"),
            "fetch_calls": _sum_unique_cost(items, "fetch_calls"),
            "successful_fetches": _sum_unique_cost(items, "successful_fetches"),
            "unique_sources_mean": _mean(item.get("unique_sources", 0) for item in items),
            "elapsed_seconds_mean": _mean(item.get("elapsed_seconds", 0.0) for item in items),
        }
    return summary


def _mean(values) -> float:
    values = [value for value in values if value is not None]
    return sum(float(value) for value in values) / len(values) if values else 0.0


def _mean_nested(items: list[dict[str, Any]], outer: str, inner: str) -> float:
    return _mean((item.get(outer) or {}).get(inner) for item in items)


def _format_coverage(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f}"


def _sum_unique_cost(items: list[dict[str, Any]], field: str) -> int:
    """Avoid multiplying shared generic search cost by cloned profiles."""

    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    total = 0
    for item in items:
        key = (
            str(item.get("task_id")),
            str(item.get("variant")),
            tuple(str(query) for query in item.get("planned_queries", [])),
        )
        if key in seen:
            continue
        seen.add(key)
        total += int(item.get(field, 0))
    return total


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line interface."""

    parser = argparse.ArgumentParser(description="Execute planner queries through web search and fetch.")
    parser.add_argument("--plan", default=str(DEFAULT_PLAN))
    parser.add_argument("--tasks", default=str(DEFAULT_TASKS))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--variant", action="append", choices=("generic", "profile_at_answer", "profile_prompt", "gap_planner")
    )
    parser.add_argument("--task-id", action="append")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--fetch-top-n", type=int, default=2)
    parser.add_argument("--max-attempts", type=int, default=4)
    return parser


def main() -> int:
    """Execute a bounded evidence probe and save its artifact."""

    _load_env()
    args = build_parser().parse_args()
    task_map = _load_tasks(Path(args.tasks))
    plan = _load_plan(Path(args.plan))
    variants = tuple(args.variant or DEFAULT_VARIANTS)
    task_ids = set(args.task_id) if args.task_id else None
    selected = _select_results(plan, variants=variants, task_ids=task_ids)

    executions: list[dict[str, Any]] = []
    gap_planner = KnowledgeStateGapPlanner()
    for index, result in enumerate(selected, 1):
        print(f"[{index}/{len(selected)}] {result.get('task_id')} {result.get('student_id')} {result.get('variant')}")
        task_id = str(result.get("task_id"))
        if task_id not in task_map:
            print(f"  skip: unknown task_id={task_id}")
            continue
        execution = execute_result(
            result,
            top_k=args.top_k,
            fetch_top_n=args.fetch_top_n,
            max_attempts=args.max_attempts,
        )
        task = task_map[task_id]
        if execution["variant"] in {"generic", "profile_at_answer"}:
            # One real search trajectory is evaluated against every profile.
            # This isolates evidence personalization from network/model noise.
            for profile in task.profiles:
                clone = dict(execution)
                clone["student_id"] = profile.student_id
                clone["profile"] = profile.to_dict()
                clone["gap"] = gap_planner.plan(task, profile).to_dict()
                clone["core_evidence_coverage"] = _match_requirements(execution["evidence_text"], clone, kind="core")
                clone["learner_evidence_coverage"] = _match_requirements(
                    execution["evidence_text"], clone, kind="learner"
                )
                clone["shared_search_execution"] = True
                executions.append(clone)
        else:
            execution["shared_search_execution"] = False
            executions.append(execution)
        print(
            f"  core={_format_coverage(execution['core_evidence_coverage']['covered'])} "
            f"learner={_format_coverage(execution['learner_evidence_coverage']['covered'])} "
            f"search={execution['search_calls']} fetch_ok={execution['successful_fetches']}"
        )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "experiment": "knowledge_state_search_evidence_probe_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config": {
            "variants": list(variants),
            "top_k": args.top_k,
            "fetch_top_n": args.fetch_top_n,
            "max_attempts": args.max_attempts,
        },
        "summary": summarize(executions),
        "executions": executions,
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    print(f"Saved evidence artifact to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
