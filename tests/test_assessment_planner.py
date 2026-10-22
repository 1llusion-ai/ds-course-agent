"""Deterministic assessment assignment planning tests."""

from __future__ import annotations

from ds_course_agent.assessment.models import Difficulty, TeachingObjectiveKind
from ds_course_agent.teaching.assessment_assignment import AssessmentAssignmentPlanner
from ds_course_agent.teaching.learner_state import (
    LearnerConceptFocus,
    LearnerStateSnapshot,
    LearnerWeakSpot,
)
from ds_course_agent.teaching.learning_events import build_concept_mentioned_event
from ds_course_agent.teaching.practice import PracticeObservation, summarize_practice


def _weak_spot(concept_id: str, *, resolved: bool = False) -> LearnerWeakSpot:
    return LearnerWeakSpot(
        concept_id=concept_id,
        display_name=concept_id,
        parent_concept=None,
        evidence_confidence=0.9,
        clarification_count=2,
        first_detected_at=1.0,
        last_triggered_at=2.0,
        resolved_at=3.0 if resolved else None,
        resolution_note="已复习" if resolved else None,
    )


def test_explicit_matched_concept_takes_priority_over_profile() -> None:
    matched = [type("Concept", (), {"concept_id": "decision_tree"})()]
    state = LearnerStateSnapshot(student_id="s1", weak_spot_candidates=(_weak_spot("svm"),))

    request = AssessmentAssignmentPlanner().plan(matched, state)

    assert request.target_kc_id == "decision_tree"
    assert request.difficulty is Difficulty.BASIC
    assert request.count == 5


def test_active_weak_spot_is_selected_at_basic_difficulty() -> None:
    state = LearnerStateSnapshot(student_id="s1", weak_spot_candidates=(_weak_spot("svm"),))

    request = AssessmentAssignmentPlanner().plan((), state)

    assert request.target_kc_id == "svm"
    assert request.difficulty is Difficulty.BASIC


def test_repeated_mentions_do_not_claim_practice_readiness() -> None:
    focus = LearnerConceptFocus(
        concept_id="cross_validation",
        display_name="交叉验证",
        chapter="第5章",
        mention_count=3,
        first_mentioned_at=1.0,
        last_mentioned_at=2.0,
        last_question_type="concept_qa",
    )
    state = LearnerStateSnapshot(student_id="s1", recent_concepts={focus.concept_id: focus})

    request = AssessmentAssignmentPlanner().plan((), state)

    assert request.target_kc_id == "cross_validation"
    assert request.difficulty is Difficulty.BASIC


def test_self_reported_resolution_does_not_skip_basic_practice() -> None:
    resolved = _weak_spot("regularization", resolved=True)
    state = LearnerStateSnapshot(student_id="s1", resolved_weak_spots=(resolved,))

    request = AssessmentAssignmentPlanner().plan(
        [type("Concept", (), {"concept_id": "regularization"})()],
        state,
    )

    assert request.difficulty is Difficulty.BASIC


def test_session_planning_prioritizes_weak_spots_and_caps_new_kcs() -> None:
    events = [
        build_concept_mentioned_event("session", "s1", concept_id, concept_id, "第8章", "concept_qa", 1.0, concept_id)
        for concept_id in ("overfitting", "underfitting", "svm", "decision_tree")
    ]
    state = LearnerStateSnapshot(student_id="s1", weak_spot_candidates=(_weak_spot("svm"),))

    plans = AssessmentAssignmentPlanner().plan_session("session", events, state)

    assert [plan.request.target_kc_id for plan in plans] == ["svm", "overfitting", "underfitting"]
    assert all(plan.request.count == 2 for plan in plans)
    requirement = plans[0].request.teaching_requirement
    assert requirement is not None
    assert {objective.kind for objective in requirement.objectives} == {
        TeachingObjectiveKind.CONCEPT_DISTINCTION,
        TeachingObjectiveKind.APPLICATION_TRANSFER,
    }


def test_session_planning_counts_existing_preparations_and_ignores_duplicate_mentions() -> None:
    events = [
        build_concept_mentioned_event("session", "s1", concept_id, concept_id, "第8章", "concept_qa", 1.0, concept_id)
        for concept_id in ("overfitting", "underfitting", "svm", "decision_tree")
    ]
    planner = AssessmentAssignmentPlanner()
    state = LearnerStateSnapshot(student_id="s1")

    initial = planner.plan_session("session", events, state)
    consumed = {plan.request.target_kc_id: (plan.context.opportunity_id,) for plan in initial}
    remaining = planner.plan_session(
        "session",
        events + [events[0]],
        state,
        consumed_opportunities={key: value for key, value in consumed.items() if key != "svm"},
    )
    exhausted = planner.plan_session("session", events, state, consumed_opportunities=consumed)

    assert [plan.request.target_kc_id for plan in remaining] == ["svm"]
    assert exhausted == ()


def test_recent_wrong_operation_changes_the_next_teaching_objective() -> None:
    practice = summarize_practice(
        [
            (
                1.0,
                PracticeObservation(
                    assessment_id="a1",
                    question_id="q1",
                    concept_id="pca",
                    display_name="主成分分析",
                    difficulty="basic",
                    is_correct=False,
                    response_time_ms=100,
                    selected_option_id="A",
                    correct_option_id="B",
                    question_stem="为什么标准化会改变 PCA 的方向？",
                    cognitive_operation="interpretation",
                    objective_kind="concept_distinction",
                ),
            )
        ]
    )
    state = LearnerStateSnapshot(student_id="s1", practice={"pca": practice})

    request = AssessmentAssignmentPlanner().plan_for_concept("pca", state, count=2)

    assert request.teaching_requirement is not None
    assert "关系解释" in request.teaching_requirement.objectives[0].objective


def test_same_score_with_different_errors_produces_different_bounded_tasks() -> None:
    from ds_course_agent.assessment.evidence import resolve_target
    from ds_course_agent.assessment.task_context import AssessmentTaskContext

    def request_for(operation: str, stem: str):
        observation = PracticeObservation(
            assessment_id="assessment-private",
            question_id="question-private",
            concept_id="pca",
            display_name="主成分分析",
            difficulty="basic",
            is_correct=False,
            response_time_ms=100,
            selected_option_id="A",
            correct_option_id="B",
            question_stem=stem,
            selected_option_text="学生实际选择",
            correct_option_text="经过审核的正确选项",
            cognitive_operation=operation,
        )
        practice = summarize_practice([(1.0, observation)])
        other = summarize_practice(
            [
                (
                    1.0,
                    observation.__class__(
                        **{**observation.__dict__, "concept_id": "svm", "question_stem": "OTHER_KC_SECRET"}
                    ),
                )
            ]
        )
        state = LearnerStateSnapshot(student_id="STUDENT_ID_SECRET", practice={"pca": practice, "svm": other})
        return AssessmentAssignmentPlanner().plan_for_concept("pca", state, count=2)

    distinction = request_for("interpretation", "为什么主成分之间相互正交？")
    application = request_for("application", "两个特征尺度不同，如何选择 PCA 的预处理？")
    assert distinction.difficulty == application.difficulty == Difficulty.BASIC
    assert distinction.learner_evidence.recent_answered_count == application.learner_evidence.recent_answered_count
    assert distinction.task_fingerprint(0) != application.task_fingerprint(0)
    context = AssessmentTaskContext(distinction, resolve_target(distinction))
    prompt = context.learner_text()
    assert "为什么主成分之间相互正交" in prompt
    assert "学生实际选择" in prompt and "经过审核的正确选项" in prompt
    assert "OTHER_KC_SECRET" not in prompt and "STUDENT_ID_SECRET" not in prompt
    assert "为什么主成分之间相互正交" not in context.target_text()


def test_profile_projection_keeps_at_most_two_errors_and_does_not_invent_unknown_operations() -> None:
    observations = [
        (
            float(index),
            PracticeObservation(
                assessment_id=f"a{index}",
                question_id=f"q{index}",
                concept_id="pca",
                display_name="主成分分析",
                difficulty="basic",
                is_correct=False,
                response_time_ms=100,
                selected_option_id="A",
                correct_option_id="B",
                question_stem=f"第 {index} 次主成分分析错误记录？",
            ),
        )
        for index in range(4)
    ]
    state = LearnerStateSnapshot(student_id="s", practice={"pca": summarize_practice(observations)})
    request = AssessmentAssignmentPlanner().plan_for_concept("pca", state, count=2)
    assert len(request.learner_evidence.recent_errors) == 2
    assert all(error.cognitive_operation is None for error in request.learner_evidence.recent_errors)
    assert request.learner_evidence.effective_answered_count == 4
