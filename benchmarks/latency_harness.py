"""
Lightweight latency harness for the RAG agent.

Runs a fixed set of benchmark queries through ``core_bridge.chat_with_history``
and writes a JSON latency/trace report.  This intentionally measures only
end-to-end wall-clock latency in v1; true streaming TTFB is not captured here.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_BENCHMARK_PATH = Path(__file__).parent / "data" / "agent_tasks_v1.json"
DEFAULT_REPORT_PATH = Path("var") / "artifacts" / "benchmarks" / "latency_harness_report.json"
DEFAULT_STUDENT_ID = "latency_harness_student"

FORCE_GROUNDED_STAGE = "agent.force_grounded"
RETRIEVAL_GUARD_FORCE_STAGE = "retrieval_guard.force"


def safe_print(text: str) -> None:
    """Print text without crashing on terminals with narrow encodings."""
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "utf-8"
        print(text.encode(encoding, errors="replace").decode(encoding))


def _utcish_now() -> str:
    """Return an ISO timestamp using the local timezone when available."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_ms(value: Any) -> float | None:
    number = _to_float(value)
    if number is None:
        return None
    return round(number, 3)


def _percentile(sorted_values: list[float], percentile: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]

    rank = (len(sorted_values) - 1) * (percentile / 100.0)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return sorted_values[low]

    lower = sorted_values[low]
    upper = sorted_values[high]
    return lower + (upper - lower) * (rank - low)


def _stats(values: list[Any]) -> dict[str, Any]:
    numbers = [float(value) for value in values if _to_float(value) is not None]
    if not numbers:
        return {
            "count": 0,
            "min": None,
            "p50": None,
            "p95": None,
            "max": None,
            "avg": None,
        }

    ordered = sorted(numbers)
    return {
        "count": len(ordered),
        "min": round(ordered[0], 3),
        "p50": round(_percentile(ordered, 50) or 0.0, 3),
        "p95": round(_percentile(ordered, 95) or 0.0, 3),
        "max": round(ordered[-1], 3),
        "avg": round(sum(ordered) / len(ordered), 3),
    }


def _top_stage_events(result: dict[str, Any], *, limit: int = 5) -> list[dict[str, Any]]:
    """Return the slowest traced stage events for a single benchmark result."""
    trace = result.get("query_trace") if isinstance(result.get("query_trace"), dict) else {}
    events = trace.get("stage_duration_events") if isinstance(trace, dict) else []
    if not isinstance(events, list):
        return []

    stage_events: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        duration_ms = _round_ms(event.get("duration_ms"))
        if duration_ms is None:
            continue
        stage_events.append(
            {
                "stage": str(event.get("stage") or "unknown"),
                "status": event.get("status"),
                "duration_ms": duration_ms,
                "offset_ms": _round_ms(event.get("offset_ms")),
            }
        )

    stage_events.sort(key=lambda item: item["duration_ms"], reverse=True)
    return stage_events[:limit]


def _slow_query_diagnostics(results: list[dict[str, Any]], *, limit: int = 5) -> list[dict[str, Any]]:
    """Summarize the slowest queries with their dominant trace stages."""
    ordered = sorted(
        results,
        key=lambda item: _to_float(item.get("total_latency_ms")) or 0.0,
        reverse=True,
    )

    diagnostics: list[dict[str, Any]] = []
    for result in ordered[:limit]:
        diagnostics.append(
            {
                "query_id": result.get("query_id"),
                "task_id": result.get("task_id"),
                "category": result.get("category", ""),
                "route": result.get("route") or "unknown",
                "used_retrieval": bool(result.get("used_retrieval")),
                "total_latency_ms": _round_ms(result.get("total_latency_ms")),
                "query_trace_duration_ms": _round_ms(result.get("query_trace_duration_ms")),
                "content_chars": result.get("content_chars"),
                "query_preview": str(result.get("query") or "")[:120],
                "top_stage_events": _top_stage_events(result, limit=5),
            }
        )
    return diagnostics


def _stage_hotspots(stage_values: dict[str, list[float]], *, limit: int = 10) -> list[dict[str, Any]]:
    """Rank traced stages by p95 latency, then max latency."""
    rows: list[dict[str, Any]] = []
    for stage, durations in stage_values.items():
        stats = _stats(durations)
        if stats["count"] <= 0:
            continue
        rows.append(
            {
                "stage": stage,
                "count": stats["count"],
                "p50": stats["p50"],
                "p95": stats["p95"],
                "max": stats["max"],
                "avg": stats["avg"],
            }
        )

    rows.sort(
        key=lambda item: (
            _to_float(item.get("p95")) or 0.0,
            _to_float(item.get("max")) or 0.0,
            _to_float(item.get("avg")) or 0.0,
        ),
        reverse=True,
    )
    return rows[:limit]


def load_fixed_queries(
    benchmark_path: Path | str = DEFAULT_BENCHMARK_PATH,
    limit: int | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Load benchmark task turns as a deterministic query list."""
    path = Path(benchmark_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    metadata = {key: value for key, value in payload.items() if key != "tasks"}

    queries: list[dict[str, Any]] = []
    tasks = payload.get("tasks", [])
    if not isinstance(tasks, list):
        raise ValueError(f"Expected 'tasks' list in benchmark file: {path}")

    for task_index, task in enumerate(tasks, 1):
        if not isinstance(task, dict):
            continue

        task_id = str(task.get("id") or f"task_{task_index:03d}")
        turns = task.get("turns") or []
        if not isinstance(turns, list):
            continue

        for turn_index, query in enumerate(turns, 1):
            if limit is not None and len(queries) >= limit:
                return metadata, queries
            if query is None:
                continue

            queries.append(
                {
                    "query_id": f"{task_id}#turn{turn_index}",
                    "task_id": task_id,
                    "category": task.get("category", ""),
                    "description": task.get("description", ""),
                    "turn_index": turn_index,
                    "query": str(query),
                }
            )

    return metadata, queries


def _query_trace_events(query_trace: Any) -> list[dict[str, Any]]:
    if not isinstance(query_trace, dict):
        return []
    events = query_trace.get("events") or []
    return [event for event in events if isinstance(event, dict)]


def extract_query_trace_metrics(query_trace: Any) -> dict[str, Any]:
    """Extract route, force flags, and per-stage durations from query trace."""
    if not isinstance(query_trace, dict):
        query_trace = {}

    events = _query_trace_events(query_trace)
    stage_durations_ms: dict[str, list[float]] = defaultdict(list)
    stage_duration_events: list[dict[str, Any]] = []
    route: str | None = None

    for event in events:
        stage = str(event.get("stage") or "")
        data = event.get("data") if isinstance(event.get("data"), dict) else {}

        event_route = data.get("route")
        if event_route:
            route = str(event_route)

        duration_ms = _round_ms(data.get("duration_ms"))
        if duration_ms is not None:
            stage_durations_ms[stage].append(duration_ms)
            stage_duration_events.append(
                {
                    "stage": stage,
                    "status": event.get("status"),
                    "duration_ms": duration_ms,
                    "offset_ms": event.get("offset_ms"),
                }
            )

    return {
        "trace_id": query_trace.get("trace_id"),
        "status": query_trace.get("status"),
        "duration_ms": _round_ms(query_trace.get("duration_ms")),
        "event_count": len(events),
        "error_count": len(query_trace.get("errors") or []),
        "errors": query_trace.get("errors") or [],
        "route": route or "unknown",
        "stage_durations_ms": dict(stage_durations_ms),
        "stage_duration_events": stage_duration_events,
        "agent_force_grounded": any(event.get("stage") == FORCE_GROUNDED_STAGE for event in events),
        "retrieval_guard_force": any(event.get("stage") == RETRIEVAL_GUARD_FORCE_STAGE for event in events),
    }


@contextmanager
def maybe_isolated_benchmark_environment(warnings: list[str]) -> Iterator[Path | None]:
    """
    Reuse the existing benchmark sandbox when available.

    The latency harness still works without it, but the sandbox avoids polluting
    persistent chat history/profile state during local benchmark runs.
    """
    try:
        from benchmarks.agent_benchmark import isolated_benchmark_environment
    except Exception as exc:  # pragma: no cover - only exercised with broken deps/imports
        warnings.append(f"isolated_benchmark_environment unavailable: {type(exc).__name__}: {exc}")
        yield None
        return

    with isolated_benchmark_environment() as temp_dir:
        yield temp_dir


def run_single_query(
    query_spec: dict[str, Any],
    *,
    student_id: str,
    session_id: str,
) -> dict[str, Any]:
    """Run one query through core_bridge and return latency/trace metrics."""
    start_perf = time.perf_counter()
    error: dict[str, str] | None = None
    response: dict[str, Any] = {}

    try:
        from ds_course_agent.api import core_bridge

        raw_response = core_bridge.chat_with_history(
            message=query_spec["query"],
            session_id=session_id,
            student_id=student_id,
        )
        response = raw_response if isinstance(raw_response, dict) else {"content": str(raw_response)}
    except Exception as exc:  # pragma: no cover - core_bridge usually captures agent errors
        error = {"type": type(exc).__name__, "message": str(exc)}

    total_latency_ms = round((time.perf_counter() - start_perf) * 1000, 3)
    query_trace = response.get("query_trace") if isinstance(response, dict) else {}
    trace_metrics = extract_query_trace_metrics(query_trace)

    sources = response.get("sources") if isinstance(response, dict) else []
    if not isinstance(sources, list):
        sources = []

    content = response.get("content", "") if isinstance(response, dict) else ""
    if content is None:
        content = ""
    content = str(content)

    return {
        "query_id": query_spec["query_id"],
        "task_id": query_spec["task_id"],
        "category": query_spec.get("category", ""),
        "description": query_spec.get("description", ""),
        "turn_index": query_spec["turn_index"],
        "query": query_spec["query"],
        "session_id": session_id,
        "student_id": student_id,
        "total_latency_ms": total_latency_ms,
        "route": trace_metrics["route"],
        "used_retrieval": bool(response.get("used_retrieval")) if isinstance(response, dict) else False,
        "sources_count": len(sources),
        "query_trace": {
            "trace_id": trace_metrics["trace_id"],
            "status": trace_metrics["status"],
            "duration_ms": trace_metrics["duration_ms"],
            "event_count": trace_metrics["event_count"],
            "error_count": trace_metrics["error_count"],
            "errors": trace_metrics["errors"],
            "stage_durations_ms": trace_metrics["stage_durations_ms"],
            "stage_duration_events": trace_metrics["stage_duration_events"],
        },
        "query_trace_duration_ms": trace_metrics["duration_ms"],
        "agent_force_grounded": trace_metrics["agent_force_grounded"],
        "retrieval_guard_force": trace_metrics["retrieval_guard_force"],
        "content_chars": len(content),
        "content_preview": content[:200],
        "error": error,
    }


def build_latency_report(
    *,
    benchmark_metadata: dict[str, Any],
    benchmark_path: Path | str,
    output_path: Path | str,
    student_id: str,
    limit: int | None,
    started_at: str,
    finished_at: str,
    isolated_environment: bool,
    warnings: list[str],
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    total_queries = len(results)
    route_counts = Counter(result.get("route") or "unknown" for result in results)
    stage_values: dict[str, list[float]] = defaultdict(list)
    for result in results:
        for stage, durations in result["query_trace"]["stage_durations_ms"].items():
            stage_values[stage].extend(durations)

    return {
        "metadata": {
            "harness_name": "latency_harness",
            "version": "0.1",
            "generated_at": finished_at,
            "started_at": started_at,
            "finished_at": finished_at,
            "benchmark": {
                "path": str(benchmark_path),
                **benchmark_metadata,
            },
            "output_path": str(output_path),
            "student_id": student_id,
            "limit": limit,
            "ttfb_ms": None,
            "notes": [
                "v1 measures total wall-clock latency around core_bridge.chat_with_history.",
                "True streaming TTFB is intentionally not measured in this harness.",
            ],
            "runtime": {
                "python": sys.version.split()[0],
                "isolated_benchmark_environment": isolated_environment,
            },
            "warnings": warnings,
        },
        "summary": {
            "total_queries": total_queries,
            "completed_queries": sum(1 for result in results if result.get("error") is None),
            "error_queries": sum(1 for result in results if result.get("error") is not None),
            "query_trace_error_status_count": sum(
                1 for result in results if result["query_trace"].get("status") == "error"
            ),
            "latency_ms": _stats([result["total_latency_ms"] for result in results]),
            "query_trace_duration_ms": _stats(
                [
                    result["query_trace"].get("duration_ms")
                    for result in results
                    if result["query_trace"].get("duration_ms") is not None
                ]
            ),
            "routes": dict(route_counts),
            "used_retrieval_count": sum(1 for result in results if result.get("used_retrieval")),
            "used_retrieval_rate": (
                sum(1 for result in results if result.get("used_retrieval")) / total_queries if total_queries else 0.0
            ),
            "avg_sources_count": (
                round(sum(result.get("sources_count", 0) for result in results) / total_queries, 3)
                if total_queries
                else 0.0
            ),
            "agent_force_grounded_count": sum(1 for result in results if result.get("agent_force_grounded")),
            "retrieval_guard_force_count": sum(1 for result in results if result.get("retrieval_guard_force")),
            "stage_duration_ms": {
                stage: _stats(durations) for stage, durations in sorted(stage_values.items(), key=lambda item: item[0])
            },
            "stage_hotspots": _stage_hotspots(stage_values),
            "slow_queries": _slow_query_diagnostics(results),
        },
        "results": results,
    }


def run_latency_harness(
    *,
    benchmark_path: Path | str = DEFAULT_BENCHMARK_PATH,
    output_path: Path | str = DEFAULT_REPORT_PATH,
    limit: int | None = None,
    student_id: str = DEFAULT_STUDENT_ID,
) -> dict[str, Any]:
    if limit is not None and limit < 0:
        raise ValueError("--limit must be non-negative")

    started_at = _utcish_now()
    benchmark_metadata, queries = load_fixed_queries(benchmark_path, limit=limit)
    warnings: list[str] = []
    results: list[dict[str, Any]] = []
    isolated_environment = False

    safe_print(f"Running latency harness: {len(queries)} queries")
    safe_print("=" * 60)

    with maybe_isolated_benchmark_environment(warnings) as temp_dir:
        isolated_environment = temp_dir is not None
        for index, query_spec in enumerate(queries, 1):
            session_id = f"latency_harness_{query_spec['task_id']}"
            result = run_single_query(
                query_spec,
                student_id=student_id,
                session_id=session_id,
            )
            results.append(result)

            status = "ERROR" if result.get("error") else "OK"
            safe_print(
                f"[{index}/{len(queries)}] {query_spec['query_id']} {status} | "
                f"{result['total_latency_ms']:.1f} ms | route={result['route']} | "
                f"retrieval={result['used_retrieval']}"
            )

    finished_at = _utcish_now()
    report = build_latency_report(
        benchmark_metadata=benchmark_metadata,
        benchmark_path=benchmark_path,
        output_path=output_path,
        student_id=student_id,
        limit=limit,
        started_at=started_at,
        finished_at=finished_at,
        isolated_environment=isolated_environment,
        warnings=warnings,
        results=results,
    )

    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    safe_print("=" * 60)
    safe_print(f"Latency p50: {report['summary']['latency_ms']['p50']} ms")
    safe_print(f"Latency p95: {report['summary']['latency_ms']['p95']} ms")
    safe_print(f"Routes: {report['summary']['routes']}")
    hotspots = report["summary"].get("stage_hotspots") or []
    if hotspots:
        safe_print("Top stage hotspots by p95:")
        for hotspot in hotspots[:5]:
            safe_print(
                f"  - {hotspot['stage']}: p95={hotspot['p95']} ms, max={hotspot['max']} ms, count={hotspot['count']}"
            )
    slow_queries = report["summary"].get("slow_queries") or []
    if slow_queries:
        safe_print("Slowest queries:")
        for item in slow_queries[:3]:
            safe_print(f"  - {item['query_id']}: {item['total_latency_ms']} ms, route={item['route']}")
    safe_print(f"Saved report to: {output_file}")

    return report


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the agent latency harness")
    parser.add_argument(
        "--benchmark",
        default=str(DEFAULT_BENCHMARK_PATH),
        help="Path to the benchmark JSON file used as fixed query source",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only run the first N fixed queries",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_REPORT_PATH),
        help="Where to save the JSON latency report",
    )
    parser.add_argument(
        "--student-id",
        default=DEFAULT_STUDENT_ID,
        help="Student id passed to core_bridge.chat_with_history",
    )
    return parser


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    args = build_arg_parser().parse_args()
    run_latency_harness(
        benchmark_path=args.benchmark,
        output_path=args.output,
        limit=args.limit,
        student_id=args.student_id,
    )
