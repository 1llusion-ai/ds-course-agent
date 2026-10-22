"""Regressions for shared targets, stable objectives and cognitive repair."""

import pytest

from ds_course_agent.assessment.evidence import resolve_target
from ds_course_agent.assessment.generator import AssessmentGenerator
from ds_course_agent.assessment.models import Difficulty, GeneratedQuestion
from ds_course_agent.assessment.service import AssessmentSlotFailureError
from ds_course_agent.teaching.assessment_assignment import AssessmentAssignmentPlanner
from tests.test_assessment_core import (
    PCA_EVIDENCE,
    _Critic,
    _critique_payload,
    _Document,
    _quiz_payload,
    _service_with_model,
    _StructuredModel,
    _Verifier,
)


def _pair():
    request = AssessmentAssignmentPlanner().plan_for_concept("pca", None, count=2)
    payload = _quiz_payload(2, Difficulty.BASIC)
    questions = [GeneratedQuestion.model_validate(item) for item in payload["questions"]]
    critiques = [_critique_payload(index, question) for index, question in enumerate(questions)]
    for critique, operation in zip(critiques, ("interpretation", "application"), strict=True):
        critique["cognitive_operation"] = operation
    return request, payload, critiques


def test_generation_receives_the_resolved_name_and_observable_slot_tasks():
    request, payload, critiques = _pair()
    model = _StructuredModel(payload)
    service, _ = _service_with_model(model, critic=_Critic([critiques]), documents=[_Document(PCA_EVIDENCE)])

    service.generate(request)

    prompt = model.message_batches[0][-1].content
    assert resolve_target(request).name in prompt
    assert "比较" in prompt and "recall" in prompt
    assert "pca:slot:0" in prompt and "pca:slot:1" in prompt
    assert "按 slot_index 顺序" in prompt


def test_profile_changes_author_input_but_cannot_anchor_either_blind_review():
    from ds_course_agent.assessment.critic import AssessmentQualityCritic
    from ds_course_agent.assessment.models import AssessmentLearnerEvidence, AssessmentPracticeError, EvidenceSource
    from ds_course_agent.assessment.verifier import AssessmentEvidenceVerifier, EvidenceExcerptCatalog
    from tests.test_assessment_core import _task

    request, payload, _ = _pair()
    personalized = request.model_copy(
        update={
            "learner_evidence": AssessmentLearnerEvidence(
                course_id="data-science-intro",
                target_kc_id="pca",
                answered_count=1,
                recent_answered_count=1,
                recent_errors=(
                    AssessmentPracticeError(
                        question_stem="PROFILE_MISTAKE_SECRET", correct_option_text="OLD_ANSWER_SECRET"
                    ),
                ),
            )
        }
    )
    sources = [EvidenceSource(id="S1", text=PCA_EVIDENCE)]
    catalog = EvidenceExcerptCatalog.from_sources(sources)
    questions = [GeneratedQuestion.model_validate(item) for item in payload["questions"]]
    original, adapted = _task(request), _task(personalized)
    author_prompt = AssessmentGenerator._build_messages(adapted, sources)[-1].content
    assert "PROFILE_MISTAKE_SECRET" in author_prompt and "OLD_ANSWER_SECRET" in author_prompt
    assert AssessmentQualityCritic._build_messages(original, questions, ()) == AssessmentQualityCritic._build_messages(
        adapted, questions, ()
    )
    assert AssessmentEvidenceVerifier._build_messages(
        original, questions, catalog
    ) == AssessmentEvidenceVerifier._build_messages(adapted, questions, catalog)


def test_objective_order_does_not_change_which_slot_is_accepted():
    request, payload, critiques = _pair()
    requirement = request.teaching_requirement
    request = request.model_copy(
        update={"teaching_requirement": requirement.model_copy(update={"objectives": requirement.objectives[::-1]})}
    )
    model = _StructuredModel(payload)
    service, _ = _service_with_model(model, critic=_Critic([critiques]), documents=[_Document(PCA_EVIDENCE)])
    service._repair_rounds = 0

    quiz = service.generate(request)

    assert [review.cognitive_operation.value for review in quiz.review_certificates] == [
        "interpretation",
        "application",
    ]


def test_recall_for_interpretation_is_a_specific_repairable_failure():
    request, payload, critiques = _pair()
    critiques[0]["cognitive_operation"] = "recall"
    model = _StructuredModel(payload)
    service, _ = _service_with_model(model, critic=_Critic([critiques]), documents=[_Document(PCA_EVIDENCE)])
    service._repair_rounds = 0

    with pytest.raises(AssessmentSlotFailureError) as failed:
        service.generate(request)

    progress = failed.value.progress
    assert progress.accepted_count == 1
    assert progress.pending_count == 1
    rejection = progress.pending_slots[0].to_rejection()
    assert "cognitive_operation_mismatch" in {code.value for code in rejection.codes}
    assert "interpretation" in rejection.detail and "recall" in rejection.detail

    from ds_course_agent.assessment.feedback import QuestionRepairRequest, QuestionRepairSlot
    from ds_course_agent.assessment.task_context import AssessmentTaskContext

    repair = QuestionRepairRequest(
        context=AssessmentTaskContext(request=request, target=resolve_target(request)),
        evidence=progress.evidence,
        slots=(QuestionRepairSlot("pca:slot:0", 0, rejection),),
        accepted_questions=tuple(item.question for item in progress.accepted_slots),
    )
    prompt = AssessmentGenerator._build_revision_messages(repair)[-1].content
    assert "cognitive_operation_mismatch" in prompt
    assert "interpretation" in prompt and "recall" in prompt
    assert "比较" in prompt


def test_transient_review_failure_rechecks_the_candidate_without_an_editor_call():
    from ds_course_agent.assessment.verifier import AssessmentVerifierModelCallError

    class RecoveringVerifier(_Verifier):
        failed_once = False

        def verify(self, context, questions, catalog):
            if not self.failed_once:
                self.failed_once = True
                raise AssessmentVerifierModelCallError("temporary outage")
            return super().verify(context, questions, catalog)

    request, payload, critiques = _pair()
    model = _StructuredModel(payload)
    service, _ = _service_with_model(
        model,
        verifier=RecoveringVerifier(),
        critic=_Critic([critiques]),
        documents=[_Document(PCA_EVIDENCE)],
    )
    quiz = service.generate(request)
    assert len(quiz.questions) == 2
    assert model.invoke_count == 1
    assert quiz.repair_round == 1
    assert len(service._verifier.calls) == 1


@pytest.mark.parametrize(
    "permanent, budget, critic_permanent", [(True, 2, False), (False, 0, False), (False, 2, False), (False, 2, True)]
)
def test_review_outage_preserves_unrelated_content_failure_and_respects_retry_policy(
    permanent, budget, critic_permanent
):
    from ds_course_agent.assessment.critic import AssessmentCritiqueError
    from ds_course_agent.assessment.feedback import AssessmentFailureKind, QuestionRejectionCode
    from ds_course_agent.assessment.models import GenerateQuestionsRequest
    from ds_course_agent.assessment.verifier import AssessmentVerifierModelCallError

    class UnavailableVerifier(_Verifier):
        attempts = 0

        def verify(self, context, questions, catalog):
            self.attempts += 1
            raise AssessmentVerifierModelCallError(
                "test outage",
                failure_kind=(
                    AssessmentFailureKind.PROVIDER_PERMANENT_FAILURE
                    if permanent
                    else AssessmentFailureKind.PROVIDER_TRANSIENT_FAILURE
                ),
            )

    class NoEditor:
        def revise_items(self, request):
            raise AssertionError("unreviewed content must not be rewritten during a reviewer outage")

    class UnavailableCritic(_Critic):
        def critique_batch(self, *args):
            if critic_permanent:
                raise AssessmentCritiqueError(
                    "configuration error", failure_kind=AssessmentFailureKind.PROVIDER_PERMANENT_FAILURE
                )
            return super().critique_batch(*args)

    payload = _quiz_payload(2, Difficulty.BASIC)
    payload["questions"][1]["source_ids"] = ["UNKNOWN"]
    verifier = UnavailableVerifier()
    service, _ = _service_with_model(
        _StructuredModel(payload),
        verifier=verifier,
        critic=UnavailableCritic(),
        editor=NoEditor(),
        documents=[_Document(PCA_EVIDENCE)],
    )
    service._repair_rounds = budget
    with pytest.raises(AssessmentSlotFailureError) as failed:
        service.generate(GenerateQuestionsRequest(target_kc_id="pca", count=2))

    failures = {slot.slot_index: slot for slot in failed.value.progress.pending_slots}
    assert failures[0].rejection_codes == (QuestionRejectionCode.REVIEWER_UNAVAILABLE,)
    assert failures[1].rejection_codes == (QuestionRejectionCode.UNKNOWN_SOURCE,)
    assert verifier.attempts == (1 if permanent or critic_permanent or not budget else 2)
    assert failed.value.progress.retryable is not (permanent or critic_permanent)


def test_repair_and_progress_reject_crossed_slot_identity():
    from pydantic import ValidationError

    from ds_course_agent.assessment.feedback import (
        AssessmentGenerationProgress,
        QuestionRejection,
        QuestionRejectionCode,
        QuestionRepairRequest,
        QuestionRepairSlot,
    )
    from ds_course_agent.assessment.models import EvidenceSource
    from tests.test_assessment_core import _task

    request, _, _ = _pair()
    rejection = QuestionRejection((QuestionRejectionCode.QUESTION_COUNT_SHORTFALL,))
    evidence = (EvidenceSource(id="S1", text=PCA_EVIDENCE),)
    with pytest.raises(ValueError, match="own slot index"):
        QuestionRepairRequest(
            context=_task(request),
            evidence=evidence,
            slots=(QuestionRepairSlot("pca:slot:1", 0, rejection), QuestionRepairSlot("pca:slot:0", 1, rejection)),
        )
    progress = AssessmentGenerationProgress.build(
        request,
        title="PCA",
        evidence=evidence,
        accepted_by_slot={},
        pending_by_slot={0: rejection, 1: rejection},
        repair_round=0,
    ).model_dump(mode="json")
    progress["pending_slots"][0]["slot_id"] = "pca:slot:1"
    progress["pending_slots"][1]["slot_id"] = "pca:slot:0"
    with pytest.raises(ValidationError, match="own slot index"):
        AssessmentGenerationProgress.model_validate(progress)
