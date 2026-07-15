"""Large payload artifact/offload infrastructure tests."""

import json
from pathlib import Path

from ds_course_agent.rag.query_trace import begin_query_trace, end_query_trace
from ds_course_agent.shared.context_governor import ContextBudget
from ds_course_agent.shared.tool_result_store import (
    maybe_store_large_text_payload,
    store_text_artifact,
)


def test_store_text_artifact_writes_payload_and_metadata(tmp_path):
    artifact = store_text_artifact(
        "教材片段" * 4,
        location="unit.tool.result",
        payload_type="tool_result",
        source="course_rag_tool",
        metadata={"tool": "course_rag_tool", "estimated_tokens": 10},
        root=tmp_path,
    )

    payload_path = Path(artifact.path)
    metadata_path = Path(artifact.metadata_path)
    if not payload_path.is_absolute():
        from ds_course_agent.shared.paths import PROJECT_ROOT

        payload_path = PROJECT_ROOT / payload_path
        metadata_path = PROJECT_ROOT / metadata_path

    assert payload_path.exists()
    assert payload_path.read_text(encoding="utf-8") == "教材片段" * 4
    assert metadata_path.exists()

    sidecar = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert sidecar["sha256"] == artifact.sha256
    assert sidecar["metadata"]["tool"] == "course_rag_tool"
    assert sidecar["uri"].startswith("artifact://tool_results/")


def test_maybe_store_large_text_payload_records_warning_and_artifact(tmp_path, monkeypatch):
    import ds_course_agent.shared.config as config

    payload = "教材片段" * 20
    monkeypatch.setattr(config, "TOOL_RESULT_ARTIFACTS_ENABLED", True)
    monkeypatch.setattr(config, "TOOL_RESULT_ARTIFACT_DIR", str(tmp_path))

    token = begin_query_trace({"entrypoint": "unit_test"})
    result = maybe_store_large_text_payload(
        payload,
        location="tool.course_rag_tool.result",
        payload_type="tool_result",
        budget=ContextBudget(large_message_tokens=2),
        tool="course_rag_tool",
    )
    trace = end_query_trace(token)

    assert result is not None
    assert result["artifact"]["payload_type"] == "tool_result"
    assert payload == "教材片段" * 20

    artifact_path = Path(result["artifact"]["path"])
    if not artifact_path.is_absolute():
        from ds_course_agent.shared.paths import PROJECT_ROOT

        artifact_path = PROJECT_ROOT / artifact_path
    assert artifact_path.exists()
    assert artifact_path.read_text(encoding="utf-8") == payload

    stages = [event["stage"] for event in trace["events"]]
    assert "context_governor.warning" in stages
    assert "tool_result.artifact" in stages


def test_maybe_store_large_text_payload_can_be_warning_only(tmp_path, monkeypatch):
    import ds_course_agent.shared.config as config

    monkeypatch.setattr(config, "TOOL_RESULT_ARTIFACTS_ENABLED", False)
    monkeypatch.setattr(config, "TOOL_RESULT_ARTIFACT_DIR", str(tmp_path))

    result = maybe_store_large_text_payload(
        "大" * 20,
        location="unit.warning_only",
        payload_type="tool_result",
        budget=ContextBudget(large_message_tokens=2),
        tool="python_exec_tool",
    )

    assert result is not None
    assert "artifact" not in result
    assert list(tmp_path.rglob("*")) == []
