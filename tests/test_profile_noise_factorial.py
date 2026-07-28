"""Tests for the clean/noisy raw-profile versus predicted-gap factorial."""

from __future__ import annotations

from benchmarks.knowledge_state_search import profile_noise_factorial
from benchmarks.knowledge_state_search.confirmatory_pilot import (
    load_confirmatory_pilot,
)
from benchmarks.knowledge_state_search.models import StudentProfile
from benchmarks.knowledge_state_search.profile_noise_analysis import (
    summarize_profile_noise_results,
)
from benchmarks.knowledge_state_search.profile_noise_factorial import (
    DEFAULT_NOISE_SPEC,
    ProfileCondition,
    profile_for_condition,
)


def test_noisy_profile_preserves_true_signals_and_adds_fixed_distractors() -> None:
    profile = StudentProfile(
        student_id="student",
        level="intermediate",
        mastered_concepts=("core",),
        weak_concepts=("true prerequisite",),
        misconceptions=("true misconception",),
        learning_goal="neutral goal",
    )

    clean = profile_for_condition(profile, condition=ProfileCondition.CLEAN)
    noisy = profile_for_condition(profile, condition=ProfileCondition.NOISY)

    assert clean.student_id == "student__clean"
    assert clean.weak_concepts == profile.weak_concepts
    assert clean.misconceptions == profile.misconceptions
    assert noisy.student_id == "student__noisy"
    assert "true prerequisite" in noisy.weak_concepts
    assert "true misconception" in noisy.misconceptions
    assert set(DEFAULT_NOISE_SPEC.weak_concepts).issubset(noisy.weak_concepts)
    assert set(DEFAULT_NOISE_SPEC.misconceptions).issubset(noisy.misconceptions)
    assert noisy.learning_goal == DEFAULT_NOISE_SPEC.learning_goal
    assert "requirement_id" not in str(DEFAULT_NOISE_SPEC.to_dict())

    goal_preserved = profile_for_condition(
        profile,
        condition=ProfileCondition.NOISY,
        preserve_learning_goal=True,
    )
    assert goal_preserved.learning_goal == profile.learning_goal


def _result(
    *,
    cell: str,
    task_id: str,
    repeat: int,
    learner_recall: float,
) -> dict[str, object]:
    return {
        "task_id": task_id,
        "profile_id": f"{task_id}_{cell.lower()}",
        "repeat": repeat,
        "method": cell,
        "error": None,
        "metrics": {
            "learner_recall": learner_recall,
            "core_recall": 1.0,
            "strict_evidence_precision": 1.0,
        },
        "cost": {
            "logical_model_calls": 1 if cell.startswith("M1") else 2,
            "total_tokens": 100,
            "latency_seconds": 1.0,
        },
    }


def test_summary_computes_difference_in_differences_gate() -> None:
    results = []
    for task_id in ("task_a", "task_b"):
        results.extend(
            (
                _result(
                    cell="M1_CLEAN",
                    task_id=task_id,
                    repeat=1,
                    learner_recall=1.0,
                ),
                _result(
                    cell="M2_CLEAN",
                    task_id=task_id,
                    repeat=1,
                    learner_recall=1.0,
                ),
                _result(
                    cell="M1_NOISY",
                    task_id=task_id,
                    repeat=1,
                    learner_recall=0.0,
                ),
                _result(
                    cell="M2_NOISY",
                    task_id=task_id,
                    repeat=1,
                    learner_recall=1.0,
                ),
            )
        )

    summary = summarize_profile_noise_results(results)

    assert summary["learner_interaction"]["mean_interaction"] == 1.0
    assert summary["paired"]["M2_vs_M1_noisy"]["learner_recall"]["mean_delta"] == 1.0
    assert summary["decision_gate"]["positive_noisy_tasks"] == 2
    assert summary["decision_gate"]["passed"] is True


def test_runner_uses_free_m2_executor_and_never_injects_gold_ids(monkeypatch) -> None:
    planner_calls = []
    predictor_profiles = []

    def fake_predict_obligations(**kwargs):
        profile = kwargs["profile"]
        predictor_profiles.append(profile)
        return {
            "prediction": {
                "obligations": [
                    {
                        "kind": "prerequisite",
                        "concept": "derivative",
                        "claim": "derivative evidence",
                        "search_terms": ["derivative slope"],
                        "trigger": {
                            "field": "weak_concept",
                            "value": profile.weak_concepts[0],
                        },
                        "priority": 1,
                    }
                ]
            },
            "telemetry": {
                "prompt_tokens": 10,
                "completion_tokens": 2,
                "total_tokens": 12,
                "latency_seconds": 0.1,
            },
            "error": None,
        }

    def fake_run_planner_case(**kwargs):
        planner_calls.append(kwargs)
        return {
            "task_id": kwargs["task_id"],
            "profile_id": kwargs["profile"].student_id,
            "repeat": kwargs["repeat"],
            "method": kwargs["method"],
            "error": None,
            "metrics": {
                "learner_recall": 1.0,
                "core_recall": 1.0,
                "strict_evidence_precision": 1.0,
            },
            "cost": {
                "logical_model_calls": 1 + kwargs.get("predictor_calls", 0),
                "total_tokens": 100,
                "latency_seconds": 1.0,
            },
            **kwargs["extra"],
        }

    monkeypatch.setattr(
        profile_noise_factorial,
        "predict_obligations",
        fake_predict_obligations,
    )
    monkeypatch.setattr(
        profile_noise_factorial,
        "_run_planner_case",
        fake_run_planner_case,
    )

    report = profile_noise_factorial.run_profile_noise_factorial(
        api_key="test",
        base_url="http://unused",
        model="test",
        schema=load_confirmatory_pilot(),
        task_ids=("gd_learning_rate",),
        repeats=1,
    )

    assert report["executed_model_calls"] == 6
    assert len(planner_calls) == 4
    assert len(predictor_profiles) == 2
    m2_calls = [call for call in planner_calls if call["method"].startswith("M2")]
    assert all(call["variant"] == "gap_planner" for call in m2_calls)
    assert all(call["enforce_target_contract"] is False for call in m2_calls)
    assert all("claim_id" not in str(call["profile"].to_dict()) for call in planner_calls)
    assert set(report["summary"]["cells"]) == {
        "M1_CLEAN",
        "M1_NOISY",
        "M2_CLEAN",
        "M2_NOISY",
    }
