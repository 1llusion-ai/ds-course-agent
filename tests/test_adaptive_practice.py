"""Offline invariants for scored-evidence opportunities and stable difficulty."""

from dataclasses import replace

import pytest
from pydantic import ValidationError

from ds_course_agent.assessment.models import GenerateQuestionsRequest
from ds_course_agent.teaching.assessment_assignment import AssessmentAssignmentPlanner
from ds_course_agent.teaching.learner_state import LearnerStateSnapshot
from ds_course_agent.teaching.learning_events import QuestionAnsweredEvent, build_concept_mentioned_event
from ds_course_agent.teaching.practice import PracticeObservation, summarize_practice


def observation(index, *, correct=True, difficulty="basic", assessment=None, item_id=None):
    return PracticeObservation(
        assessment_id=assessment or f"round-{index // 2}",
        question_id=f"q-{index}",
        concept_id="overfitting",
        display_name="过拟合",
        difficulty=difficulty,
        is_correct=correct,
        response_time_ms=100,
        selected_option_id="A",
        correct_option_id="A",
        question_stem=f"独立题目{index}",
        item_id=item_id or f"item-{index}",
    )


def test_difficulty_uses_distinct_items_and_has_one_step_hysteresis():
    records = [(index, observation(index, difficulty="basic" if index < 2 else "intermediate")) for index in range(4)]
    assert summarize_practice(records[:2]).recommended_difficulty == "intermediate"
    assert summarize_practice(records).recommended_difficulty == "advanced"
    records.append((4, observation(4, correct=False, difficulty="advanced")))
    assert summarize_practice(records).recommended_difficulty == "advanced"
    records.append((5, observation(5, correct=False, difficulty="advanced")))
    assert summarize_practice(records).recommended_difficulty == "intermediate"
    records.append((6, observation(6, difficulty="intermediate")))
    assert summarize_practice(records).recommended_difficulty == "intermediate"
    records.append((7, observation(7, item_id="item-6", difficulty="intermediate")))
    summary = summarize_practice(records)
    assert summary.effective_answered_count == 7
    assert summary.recommended_difficulty == "intermediate"


def test_same_session_new_score_replans_but_mentions_and_profile_revision_do_not():
    planner = AssessmentAssignmentPlanner()
    state = LearnerStateSnapshot(student_id="s", profile_revision=1)
    mention = build_concept_mentioned_event("session", "s", "overfitting", "过拟合", "第8章", "concept_qa", 1, "turn")
    first = planner.plan_session("session", [mention], state)[0]
    consumed = {"overfitting": (first.context.opportunity_id,)}
    assert not planner.plan_session(
        "session", [mention, mention], replace(state, profile_revision=99), consumed_opportunities=consumed
    )
    answer = QuestionAnsweredEvent(
        event_id="score", session_id="session", student_id="s", timestamp=2, observation=observation(0)
    )
    second = planner.plan_session(
        "session", [mention, answer], replace(state, profile_revision=2), consumed_opportunities=consumed
    )[0]
    assert second.context.opportunity_id != first.context.opportunity_id
    assert second.context.profile_revision == 2
    assert not planner.plan_session(
        "session", [mention, answer], state, consumed_opportunities=consumed, active_kc_ids=("overfitting",)
    )
    foreign = replace(answer, course_id="digital-literacy")
    assert not planner.plan_session("session", [mention, foreign], state, consumed_opportunities=consumed)
    # A legacy deterministic failure can recover once under the new resource policy.
    assert planner.plan_session("session", [mention], state, consumed_opportunities={"overfitting": ("initial",)})


def test_repeated_item_error_remains_feedback_without_independent_difficulty_evidence():
    records = [(index, observation(index, difficulty="basic" if index < 2 else "intermediate")) for index in range(4)]
    records.extend((index, observation(index, item_id="item-0", correct=False)) for index in (4, 5))
    summary = summarize_practice(records)
    assert summary.answered_count == 6
    assert summary.effective_answered_count == 4
    assert summary.recommended_difficulty == "advanced"
    assert summary.level.value == "needs_practice"
    assert summary.last_incorrect_stem == "独立题目5"
    assert not summary.recent_attempts[-1].is_correct


def test_generation_request_rejects_client_planning_facts():
    for field in (
        "plan_context",
        "opportunity_id",
        "profile_revision",
        "resource_revision",
        "exposure",
        "batch_review",
        "repair_round",
    ):
        with pytest.raises(ValidationError):
            GenerateQuestionsRequest.model_validate({"target_kc_id": "pca", field: "spoofed"})


def test_unversioned_or_stale_progress_cannot_reach_retrieval_or_models():
    from unittest.mock import Mock

    from ds_course_agent.assessment.feedback import (
        AssessmentGenerationProgress,
        QuestionRejection,
        QuestionRejectionCode,
    )
    from ds_course_agent.assessment.models import EvidenceSource
    from ds_course_agent.assessment.service import AssessmentResourceChangedError, AssessmentService
    from ds_course_agent.assessment.versioning import assessment_resource_revision

    request = GenerateQuestionsRequest(target_kc_id="pca", count=1)
    progress = AssessmentGenerationProgress.build(
        request,
        title="test",
        evidence=(EvidenceSource(id="S1", text="PCA是降维方法。"),),
        accepted_by_slot={},
        pending_by_slot={0: QuestionRejection((QuestionRejectionCode.QUESTION_COUNT_SHORTFALL,))},
        repair_round=0,
    )
    retriever, generator = Mock(), Mock()
    service = AssessmentService(retriever=retriever, generator=generator)
    with pytest.raises(AssessmentResourceChangedError):
        service.generate(request, progress=progress)
    current = assessment_resource_revision("data-science-intro")
    stale = progress.model_copy(update={"resource_revision": current.model_copy(update={"graph_digest": "stale"})})
    with pytest.raises(AssessmentResourceChangedError):
        service.generate(request, progress=stale)
    assert not progress.model_copy(update={"repair_round": 4}).retryable
    retriever.retrieve.assert_not_called()
    generator.generate_candidates.assert_not_called()


def test_preparation_repository_serializes_concurrent_sessions_for_same_kc(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from ds_course_agent.assessment.preparation import PreparationRepository

    repository = PreparationRepository(tmp_path / "assessment.db")
    repository.list_for_student("s")
    request = GenerateQuestionsRequest(target_kc_id="pca", count=2)
    with ThreadPoolExecutor(max_workers=2) as executor:
        jobs = list(executor.map(lambda session: repository.enqueue("s", session, "PCA", request, ()), ("a", "b")))
    assert jobs[0].id == jobs[1].id
    assert len(repository.list_for_student("s")) == 1
