"""Keep reviewed content separate from orchestration, learner state and live I/O."""

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "ds_course_agent"


@pytest.mark.parametrize("module", ["items", "versioning", "generation_constraints"])
def test_reviewed_content_owners_do_not_import_orchestration_or_live_dependencies(module: str) -> None:
    allowed = {"assessment", "courses", "shared"}
    violations = []
    path = PACKAGE / "assessment" / f"{module}.py"
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            imports = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            assert not node.level, "Content owners use explicit public package imports"
            imports = [node.module or ""]
        else:
            continue
        for name in imports:
            if name.startswith("ds_course_agent.") and name.split(".")[1] not in allowed:
                violations.append(f"{path.name}:{node.lineno}: {name}")
    assert not violations, violations


def test_shared_content_payload_cannot_acquire_learner_or_attempt_state() -> None:
    tree = ast.parse((PACKAGE / "assessment/items.py").read_text(encoding="utf-8"))
    item = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ReviewedItem")
    fields = {node.target.id for node in item.body if isinstance(node, ast.AnnAssign)}
    assert not fields & {"student_id", "session_id", "assessment_id", "question_id", "answers", "profile", "attempts"}
