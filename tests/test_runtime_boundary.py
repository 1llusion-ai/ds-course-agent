"""Dependency and behavioral contracts for the domain-independent runtime."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import Mock

import pytest
from langchain_core.messages import AIMessageChunk

from ds_course_agent.runtime.model_runtime import ModelRuntime
from ds_course_agent.shared.query_trace import begin_query_trace, end_query_trace
from tests.subprocess_utils import run_python_script

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "ds_course_agent"


def test_runtime_and_shared_imports_do_not_depend_on_domains() -> None:
    """Enforce the foundation dependency direction, including lazy imports."""

    violations = []
    allowed_layers = {
        "runtime": {"runtime", "shared"},
        "shared": {"shared"},
    }
    for layer in ("runtime", "shared"):
        for path in (PACKAGE / layer).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                modules = []
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    if node.level:
                        base = ["ds_course_agent", *path.relative_to(PACKAGE).parts[:-1]]
                        base = base[: len(base) - node.level + 1]
                        module = ".".join([*base, *(node.module or "").split(".")]).rstrip(".")
                    else:
                        module = node.module or ""
                    modules = [module]
                    if module == "ds_course_agent":
                        modules = [f"{module}.{alias.name}" for alias in node.names]
                for module in modules:
                    if module.startswith("ds_course_agent.") and module.split(".")[1] not in allowed_layers[layer]:
                        violations.append(f"{path.relative_to(PACKAGE)}:{node.lineno}: {module}")
    assert not violations, violations


def test_runtime_import_does_not_load_domain_packages() -> None:
    """A fresh interpreter must load infrastructure without starting the course agent."""

    script = """
import sys
from ds_course_agent.runtime.model_runtime import ModelRuntime
from ds_course_agent.runtime.context import govern_context_budget
from ds_course_agent.shared.query_trace import begin_query_trace, end_query_trace
from langchain_core.messages import HumanMessage
token = begin_query_trace()
govern_context_budget([HumanMessage(content='hello')], location='runtime.import_test')
end_query_trace(token)
forbidden = ('rag', 'agent', 'teaching', 'retrieval', 'assessment', 'research', 'tools', 'api', 'hooks')
loaded = [name for name in sys.modules if any(
    name == 'ds_course_agent.' + part or name.startswith('ds_course_agent.' + part + '.')
    for part in forbidden
)]
assert not loaded, loaded
"""
    result = run_python_script(script)
    assert result.returncode == 0, result.stdout + result.stderr


def test_old_runtime_and_trace_paths_are_removed() -> None:
    """Prevent legacy modules or forwarding shims from returning."""

    for name in ("model_runtime", "model_stream", "model_context", "query_trace"):
        assert not (PACKAGE / "rag" / f"{name}.py").exists()


@pytest.mark.parametrize("direct", [False, True])
def test_model_failure_uses_only_injected_fallback(direct: bool) -> None:
    """The caller, not runtime, owns domain fallback selection."""

    model = Mock()
    model.invoke.side_effect = ValueError("400 bad request")
    fallback = Mock(return_value="domain answer")
    runtime = ModelRuntime(llm=model, tool_registry=Mock(), system_prompt="", fallback=fallback)
    answer = runtime.direct_chat("question") if direct else runtime.chat("question", graph_agent=model)
    assert answer == "domain answer"
    fallback.assert_called_once_with("question")
    assert model.invoke.call_count == 1


def test_model_failure_without_fallback_does_not_inherit_other_runtime_policy() -> None:
    """Fallback configuration is instance-local and never defaults to course RAG."""

    model = Mock()
    model.invoke.side_effect = ValueError("400 bad request")
    fallback = Mock(return_value="domain answer")
    configured = ModelRuntime(llm=model, tool_registry=Mock(), system_prompt="", fallback=fallback)
    unconfigured = ModelRuntime(llm=model, tool_registry=Mock(), system_prompt="")
    assert configured.direct_chat("first") == "domain answer"
    assert "domain answer" not in unconfigured.direct_chat("second")
    fallback.assert_called_once_with("first")


@pytest.mark.parametrize("direct", [False, True])
def test_partial_stream_failure_is_never_retried(direct: bool) -> None:
    """Already published tokens cannot be replayed by model recovery."""

    def broken_stream(*args, **kwargs):
        chunk = AIMessageChunk(content="partial")
        yield chunk if direct else (chunk, {"langgraph_node": "model"})
        raise TimeoutError("stream interrupted")

    model = Mock()
    model.stream.side_effect = broken_stream
    fallback = Mock()
    runtime = ModelRuntime(llm=model, tool_registry=Mock(), system_prompt="", fallback=fallback)
    stream = runtime.direct_chat("q", stream=True) if direct else runtime.chat("q", stream=True, graph_agent=model)
    assert next(stream) == "partial"
    with pytest.raises(TimeoutError):
        next(stream)
    model.invoke.assert_not_called()
    fallback.assert_not_called()


def test_runtime_retry_records_into_callers_shared_trace(monkeypatch) -> None:
    """Moving trace ownership must not create a second request context."""

    from langchain_core.messages import AIMessage

    import ds_course_agent.runtime.model_runtime as runtime_module

    monkeypatch.setattr(runtime_module.config, "CHAT_MAX_RETRIES", 1)
    monkeypatch.setattr(runtime_module.time, "sleep", lambda seconds: None)
    model = Mock()
    model.invoke.side_effect = [TimeoutError("timeout"), AIMessage(content="recovered")]
    runtime = ModelRuntime(llm=model, tool_registry=Mock(), system_prompt="")
    token = begin_query_trace({"entrypoint": "runtime_boundary"})
    try:
        assert runtime.direct_chat("q") == "recovered"
    finally:
        trace = end_query_trace(token)
    retries = [event for event in trace["events"] if event["stage"] == "agent.retry"]
    assert len(retries) == 1
    assert retries[0]["data"]["attempt"] == 1
