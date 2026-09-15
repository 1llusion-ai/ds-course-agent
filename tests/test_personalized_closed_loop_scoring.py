from __future__ import annotations

from benchmarks.personalized_closed_loop_dataset import build_dataset
from benchmarks.personalized_closed_loop_judge import JudgeVerdict, PersonalizedClosedLoopJudge
from benchmarks.personalized_closed_loop_scoring import score_trajectory, summarize_scores


def test_score_trajectory_requires_explicit_sse_and_kc_facts() -> None:
    trajectory = build_dataset().trajectories[0]
    trace = {
        "steps": [
            {},
            {
                "terminal_type": "final",
                "primary_kc_id": "pca",
                "matched_kc_ids": ["pca"],
                "intent": "concept_qa",
                "personalized_route": False,
            },
            {},
            {
                "terminal_type": "final",
                "primary_kc_id": "pca",
                "matched_kc_ids": ["pca"],
                "intent": "concept_qa",
                "personalized_route": True,
            },
            {"profile_updated": True, "interaction_persisted": True, "cross_session_state": True},
        ]
    }
    result = score_trajectory(trajectory, trace)
    assert result["hard_gates"]["kc_correct"] is True
    assert result["passed"] is True


def test_score_trajectory_fails_missing_terminal_event() -> None:
    trajectory = build_dataset().trajectories[0]
    result = score_trajectory(trajectory, {"steps": [{}, {}, {}, {}, {}]})
    assert result["hard_gates"]["kc_correct"] is False
    assert result["passed"] is False


def test_summary_keeps_category_and_functional_failures() -> None:
    dataset = build_dataset()
    results = [
        {
            "trajectory_id": dataset.trajectories[0].id,
            "passed": False,
            "infrastructure_failed": False,
            "checks": [],
            "hard_gates": {},
        }
    ]
    summary = summarize_scores(dataset, results)
    assert summary["failed_trajectory_ids"] == [dataset.trajectories[0].id]
    assert summary["category_failures"][dataset.trajectories[0].category] == 1


def test_judge_failure_is_conservative_and_schema_valid() -> None:
    class BrokenModel:
        def with_structured_output(self, *_args, **_kwargs):
            raise RuntimeError("broken")

    verdict = PersonalizedClosedLoopJudge(model_name="test", model=BrokenModel()).judge({})
    parsed = JudgeVerdict.model_validate(verdict)
    assert parsed.needs_human_review is True
    assert parsed.kc_correct.passed is False


def test_lifecycle_checkpoint_can_consume_retry_idempotency_fact() -> None:
    trajectory = next(item for item in build_dataset().trajectories if item.category == "lifecycle_idempotency")
    trace = {
        "steps": [
            {},
            {"terminal_type": "final", "primary_kc_id": "pca", "matched_kc_ids": ["pca"], "intent": "concept_qa"},
            {},
            {"terminal_type": "final", "primary_kc_id": "pca", "matched_kc_ids": ["pca"], "intent": "concept_qa"},
            {"outcome": "incorrect"},
            {"assessment_persisted": True, "profile_updated": True},
            {
                "before_counts": {"assessments": 1, "learning_events": 1},
                "after_counts": {"assessments": 1, "learning_events": 1},
            },
            {"idempotent_persistence": True},
        ]
    }
    result = score_trajectory(trajectory, trace)
    assert any(check["name"] == "idempotent_persistence" and check["passed"] for check in result["checks"])
