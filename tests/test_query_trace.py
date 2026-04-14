from core.query_trace import begin_query_trace, end_query_trace, trace_error, trace_step


def test_query_trace_records_steps_and_errors():
    token = begin_query_trace({"entrypoint": "unit_test"})
    trace_step("unit.step.ok", value=1)

    try:
        raise RuntimeError("boom")
    except Exception as exc:
        trace_error("unit.step.failed", exc, hint="for_test")

    payload = end_query_trace(token, status="ok")

    assert payload["meta"]["entrypoint"] == "unit_test"
    assert payload["trace_id"]
    assert payload["duration_ms"] >= 0
    assert any(item["stage"] == "unit.step.ok" for item in payload["events"])
    assert any(item["stage"] == "unit.step.failed" and item["status"] == "error" for item in payload["events"])
    assert payload["errors"]
    assert payload["errors"][0]["message"] == "boom"
    assert payload["status"] == "error"

