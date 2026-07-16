from benchmarks.latency_harness import build_latency_report


def _result(query_id, latency_ms, route, stage_events):
    durations = {}
    for event in stage_events:
        durations.setdefault(event["stage"], []).append(event["duration_ms"])
    return {
        "query_id": query_id,
        "task_id": query_id.split("#", 1)[0],
        "category": "unit",
        "description": "",
        "turn_index": 1,
        "query": f"query {query_id}",
        "session_id": "sess",
        "student_id": "student",
        "total_latency_ms": latency_ms,
        "route": route,
        "used_retrieval": route == "grounded_rag",
        "sources_count": 1 if route == "grounded_rag" else 0,
        "query_trace": {
            "trace_id": f"trace-{query_id}",
            "status": "ok",
            "duration_ms": latency_ms - 10,
            "event_count": len(stage_events),
            "error_count": 0,
            "errors": [],
            "stage_durations_ms": durations,
            "stage_duration_events": stage_events,
        },
        "query_trace_duration_ms": latency_ms - 10,
        "agent_force_grounded": False,
        "retrieval_guard_force": False,
        "content_chars": 128,
        "content_preview": "preview",
        "error": None,
    }


def test_latency_report_includes_slow_query_and_stage_hotspot_diagnostics():
    report = build_latency_report(
        benchmark_metadata={"name": "unit"},
        benchmark_path="bench.json",
        output_path="report.json",
        student_id="student",
        limit=None,
        started_at="2026-07-16T00:00:00+08:00",
        finished_at="2026-07-16T00:01:00+08:00",
        isolated_environment=True,
        warnings=[],
        results=[
            _result(
                "task_a#turn1",
                1000,
                "generic_agent",
                [
                    {"stage": "prepare.router", "status": "ok", "duration_ms": 80, "offset_ms": 90},
                    {"stage": "execute.agent_chat", "status": "ok", "duration_ms": 700, "offset_ms": 900},
                ],
            ),
            _result(
                "task_b#turn1",
                2500,
                "grounded_rag",
                [
                    {"stage": "retriever.embedding_query", "status": "ok", "duration_ms": 900, "offset_ms": 950},
                    {"stage": "tool.course_rag.answer", "status": "ok", "duration_ms": 1300, "offset_ms": 2450},
                ],
            ),
        ],
    )

    summary = report["summary"]
    assert summary["slow_queries"][0]["query_id"] == "task_b#turn1"
    assert summary["slow_queries"][0]["top_stage_events"][0]["stage"] == "tool.course_rag.answer"
    assert summary["stage_hotspots"][0]["stage"] == "tool.course_rag.answer"
    assert summary["stage_hotspots"][0]["p95"] == 1300
