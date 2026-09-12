"""Deterministic assessment assignment planning tests."""

from __future__ import annotations

from ds_course_agent.assessment.models import Difficulty
from ds_course_agent.teaching.assessment_assignment import AssessmentAssignmentPlanner
from ds_course_agent.teaching.learner_state import (
    LearnerConceptFocus,
    LearnerStateSnapshot,
    LearnerWeakSpot,
)


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


def test_recent_practiced_concept_advances_to_intermediate() -> None:
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
    assert request.difficulty is Difficulty.INTERMEDIATE


def test_resolved_weak_spot_is_retested_at_advanced_difficulty() -> None:
    resolved = _weak_spot("regularization", resolved=True)
    state = LearnerStateSnapshot(student_id="s1", resolved_weak_spots=(resolved,))

    request = AssessmentAssignmentPlanner().plan(
        [type("Concept", (), {"concept_id": "regularization"})()],
        state,
    )

    assert request.difficulty is Difficulty.ADVANCED
