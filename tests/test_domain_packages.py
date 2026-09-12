"""Import and ownership invariants for migrated domain packages."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.subprocess_utils import run_python_script

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "ds_course_agent"


@pytest.mark.parametrize(
    "modules",
    [
        ("teaching.learner_state", "teaching.memory_core", "teaching.learning_events", "teaching.skill_system"),
        ("retrieval.service", "retrieval.hybrid_retriever", "retrieval.reranker"),
        ("research.pipeline", "research.policy", "research.fetch", "research.models"),
        (
            "assessment.models",
            "assessment.generator",
            "assessment.verifier",
            "assessment.critic",
            "assessment.service",
        ),
    ],
)
def test_domains_load_without_agent_service_or_api(modules) -> None:
    """Imports must not initialize the Agent through the legacy package facade."""

    script = f"""
import importlib
import sys
for name in {modules!r}:
    importlib.import_module('ds_course_agent.' + name)
assert 'ds_course_agent.agent.service' not in sys.modules
assert not any(n == 'ds_course_agent.api' or n.startswith('ds_course_agent.api.') for n in sys.modules)
"""
    result = run_python_script(script)
    assert result.returncode == 0, result.stdout + result.stderr


def test_migrated_paths_have_no_legacy_modules() -> None:
    """The former rag paths cannot remain as compatibility wrappers."""

    for module in (
        "learner_state",
        "profile_models",
        "events",
        "memory_core",
        "knowledge_mapper",
        "course_graph",
        "skill_system",
        "rag",
        "hybrid_retriever",
        "reranker",
        "web_research",
        "web_research_policy",
        "web_research_fetch",
        "web_research_models",
    ):
        assert not (PACKAGE / "rag" / f"{module}.py").exists()


def test_domain_modules_do_not_import_api() -> None:
    """HTTP adapters may depend on domains, not the other way around."""

    for layer in ("teaching", "retrieval", "research", "assessment"):
        for path in (PACKAGE / layer).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                    if node.module == "ds_course_agent":
                        names = [f"ds_course_agent.{alias.name}" for alias in node.names]
                assert not any(n == "ds_course_agent.api" or n.startswith("ds_course_agent.api.") for n in names), path
