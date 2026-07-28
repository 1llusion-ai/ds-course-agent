"""Tests for the public representation/executor attribution matrix."""

from __future__ import annotations

from benchmarks.knowledge_state_search import public_factorial
from benchmarks.knowledge_state_search.models import (
    EvidenceGap,
    EvidenceRequirement,
    SearchTask,
    StudentProfile,
)


def _fixture() -> tuple[SearchTask, StudentProfile, EvidenceGap]:
    """Build one typed task with a visible learner obligation."""

    task = SearchTask(
        task_id="task",
        question="Why?",
        target_concepts=("core",),
        evidence_requirements=(
            EvidenceRequirement(
                requirement_id="core_01",
                kind="core",
                concept="core",
                description="core",
                search_terms=("core",),
                hard=True,
            ),
            EvidenceRequirement(
                requirement_id="learner_01",
                kind="prerequisite",
                concept="prerequisite",
                description="learner",
                search_terms=("derivative slope",),
            ),
        ),
        profiles=(),
    )
    profile = StudentProfile(student_id="student", level="intermediate")
    gap = EvidenceGap(
        core_requirements=(task.evidence_requirements[0],),
        learner_requirements=(task.evidence_requirements[1],),
    )
    return task, profile, gap


def test_planner_request_free_executor_does_not_require_learner_targets(monkeypatch):
    """Free execution may annotate targets but does not fail for omission."""

    task, profile, gap = _fixture()
    captured = {}

    def fake_request(**kwargs):
        captured.update(kwargs)
        return {"error": None}

    monkeypatch.setattr(public_factorial, "_request", fake_request)

    public_factorial._planner_request(
        api_key="key",
        base_url="http://example.test/v1",
        model="model",
        task=task,
        profile=profile,
        visible_gap=gap,
        representation="M2",
        enforce_target_contract=False,
        timeout=1,
        max_retries=1,
    )

    assert captured["required_target_ids"] == ()
    assert captured["enforce_target_contract"] is False


def test_planner_request_guarded_executor_requires_visible_learner_targets(monkeypatch):
    """Guarded execution requires every visible learner target and its terms."""

    task, profile, gap = _fixture()
    captured = {}

    def fake_request(**kwargs):
        captured.update(kwargs)
        return {"error": None}

    monkeypatch.setattr(public_factorial, "_request", fake_request)

    public_factorial._planner_request(
        api_key="key",
        base_url="http://example.test/v1",
        model="model",
        task=task,
        profile=profile,
        visible_gap=gap,
        representation="M2",
        enforce_target_contract=True,
        timeout=1,
        max_retries=1,
    )

    assert captured["required_target_ids"] == ("learner_01",)
    assert captured["required_query_terms"] == {"learner_01": ("derivative slope",)}
    assert captured["enforce_target_contract"] is True


def test_factorial_summary_uses_active_profile_denominator():
    """Learner recall excludes no-gap profiles while target rate stays explicit."""

    common = {
        "method": "M2G",
        "error": None,
        "search_calls": 1,
        "selected_source_ids": ["source"],
        "metrics": {
            "hard_core_recall": 1.0,
            "learner_recall": None,
            "evidence_precision": 1.0,
            "strict_supported_rate": 1.0,
            "contradicted_rate": 0.0,
            "unannotated_rate": 0.0,
            "claim_conflict_rate": 0.0,
        },
        "visible_plan": {
            "response": {
                "actions": [
                    {"target_requirements": ["core_01"]},
                ]
            }
        },
        "representation_gap": {"learner_requirements": []},
        "evaluation_gap": {"learner_requirements": []},
    }
    active = {
        **common,
        "metrics": {**common["metrics"], "learner_recall": 1.0},
        "representation_gap": {"learner_requirements": [{"requirement_id": "learner_01"}]},
        "evaluation_gap": {"learner_requirements": [{"requirement_id": "learner_01"}]},
        "visible_plan": {
            "response": {
                "actions": [
                    {"target_requirements": ["learner_01"]},
                ]
            }
        },
    }

    summary = public_factorial._summary([common, active])["M2G"]

    assert summary["metrics"]["learner_recall"]["mean_active_profiles"] == 1.0
    assert summary["learner_target_rate"] == 1.0
    assert summary["active_profile_cases"] == 1
