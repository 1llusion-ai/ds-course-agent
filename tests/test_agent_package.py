"""Final package migration invariants for orchestration and tooling."""

from __future__ import annotations

from pathlib import Path

from tests.subprocess_utils import run_python_script

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "ds_course_agent"


def test_legacy_packages_are_absent_and_unimportable() -> None:
    """Old package directories must not survive as shims or namespace packages."""

    for name in ("rag", "hooks"):
        assert not (PACKAGE / name).exists()
    script = """
from importlib.util import find_spec
for name in ('rag', 'hooks'):
    assert find_spec('ds_course_agent.' + name) is None
"""
    result = run_python_script(script)
    assert result.returncode == 0, result.stdout + result.stderr


def test_agent_entrypoint_is_lazy_and_contracts_have_one_identity() -> None:
    """Consumers must share the same contracts without constructing a model on import."""

    script = """
import sys
import ds_course_agent.agent
assert 'ds_course_agent.agent.service' not in sys.modules
from ds_course_agent.agent import service
from ds_course_agent.agent.events import TurnEndEvent
from ds_course_agent.agent.routing import QueryPipeline, RouteExecutionResult
from ds_course_agent.agent.routing.pipeline import QueryPipeline as Pipeline
from ds_course_agent.agent.routing.models import RouteExecutionResult as Result
from ds_course_agent.tools.code_executor import PythonSandbox
from ds_course_agent.agent.hooks import HookManager
assert service._agent_service is None
assert QueryPipeline is Pipeline
assert RouteExecutionResult is Result
assert not any(n.startswith('ds_course_agent.api') for n in sys.modules)
"""
    result = run_python_script(script)
    assert result.returncode == 0, result.stdout + result.stderr
