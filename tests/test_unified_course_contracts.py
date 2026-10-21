"""Static boundaries for course identity and domain-policy ownership."""

import ast
from dataclasses import fields

import pytest

from ds_course_agent.agent.routing.models import QueryContext
from ds_course_agent.courses import CourseScopeTerm, ResolvedCourse
from ds_course_agent.shared.paths import PROJECT_ROOT

PACKAGE = PROJECT_ROOT / "src/ds_course_agent"


def test_prepared_course_has_one_typed_owner():
    names = {item.name for item in fields(QueryContext)}
    assert "course_resources" in names
    assert "course_manifest" not in names
    assert "scope_terms" not in names


@pytest.mark.parametrize("path", ["agent/routing/pipeline.py", "research/policy.py"])
def test_every_runtime_scope_call_supplies_the_prepared_course(path):
    tree = ast.parse((PACKAGE / path).read_text())
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            isinstance(node.func, ast.Name)
            and node.func.id == "assess_query_scope"
            or isinstance(node.func, ast.Attribute)
            and node.func.attr == "assess_query_scope"
        )
    ]
    assert calls
    assert all("course" in {keyword.arg for keyword in node.keywords} for node in calls)


@pytest.mark.parametrize(
    "path",
    [
        "agent/scope_guard.py",
        "agent/taxonomy.py",
        "agent/prompt.py",
        "teaching/skills/code-review/scripts/executor.py",
        "teaching/skills/personalized-explanation/scripts/executor.py",
        "teaching/skills/misconception-handling/scripts/executor.py",
    ],
)
def test_shared_student_paths_cannot_embed_a_course_name(path):
    tree = ast.parse((PACKAGE / path).read_text())
    assert not [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and "数据科学导论" in node.value
    ]


def test_resource_contracts_do_not_parse_teaching_graphs_or_import_domain_policy():
    for path in (PACKAGE / "courses").glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(("ds_course_agent.agent", "ds_course_agent.teaching"))


@pytest.mark.parametrize(
    "payload",
    [
        {"term": "比特币", "section": "5.5.1", "book_page": 0, "source_page": 164},
        {"term": "比特币", "section": "", "book_page": 148, "source_page": 164},
        {"term": 123, "section": "5.5.1", "book_page": 148, "source_page": 164},
    ],
)
def test_scope_resource_requires_a_topic_and_valid_source_location(payload):
    with pytest.raises((ValueError, TypeError)):
        CourseScopeTerm.from_dict(payload)


def test_unresolved_course_cannot_acquire_unattributed_vocabulary():
    with pytest.raises(ValueError, match="unresolved"):
        ResolvedCourse("unknown-course", scope_terms=("比特币",))


def test_personalized_skill_stream_has_no_signature_compatibility_probe():
    tree = ast.parse((PACKAGE / "agent/handlers.py").read_text())
    skill = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "SkillRouteHandler")
    assert not [
        node
        for node in ast.walk(skill)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "signature"
    ]
