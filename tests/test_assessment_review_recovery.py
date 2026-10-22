"""Exposure and combination gates must survive bounded generation recovery."""

import pytest

from ds_course_agent.assessment.application import AssessmentApplicationService
from ds_course_agent.assessment.feedback import QuestionRepairBatch
from ds_course_agent.assessment.generator import AssessmentEditorModelCallError, AssessmentGenerationError
from ds_course_agent.assessment.models import Difficulty, GenerateQuestionsRequest
from ds_course_agent.assessment.records import AnswerSubmission
from ds_course_agent.assessment.repository import AssessmentRepository
from tests.test_assessment_core import (
    PCA_EVIDENCE,
    _Critic,
    _critique_payload,
    _Document,
    _question_payload,
    _quiz_payload,
    _service_with_model,
    _StructuredModel,
    _task,
)
from tests.test_reviewed_assessment_items import selected_item


class Editor:
    def __init__(self, *, transient=False, index=2):
        self.calls = []
        self.transient = transient
        self.index = index

    def revise_items(self, request):
        self.calls.append(request)
        if self.transient and len(self.calls) == 1:
            raise AssessmentEditorModelCallError("offline transient")
        return QuestionRepairBatch.model_validate(
            {
                "revisions": [
                    {"slot_id": slot.slot_id, "question": _question_payload(self.index + index, Difficulty.BASIC)}
                    for index, slot in enumerate(request.slots)
                ]
            }
        )


def seed_batches():
    seed, _ = _service_with_model(
        _StructuredModel(
            responses=[
                _quiz_payload(1, Difficulty.BASIC),
                {"title": "PCA练习", "questions": [_question_payload(1, Difficulty.BASIC)]},
            ]
        ),
        documents=[_Document(page_content=PCA_EVIDENCE, metadata={})],
    )
    one = GenerateQuestionsRequest(target_kc_id="pca", count=1)
    return seed.generate(one), seed.generate(one)


def test_recent_item_regeneration_is_repaired_before_assignment(tmp_path):
    editor = Editor()
    model = _StructuredModel(_quiz_payload(1, Difficulty.BASIC))
    generator, _ = _service_with_model(
        model, documents=[_Document(page_content=PCA_EVIDENCE, metadata={})], editor=editor
    )
    repository = AssessmentRepository(tmp_path / "assessment.db")
    app = AssessmentApplicationService(repository, generator)
    request = GenerateQuestionsRequest(target_kc_id="pca", count=1)
    first = app.assign("s", request)
    opened = app.open(first.id, "s")
    app.submit(
        first.id,
        "s",
        [AnswerSubmission(question_id=opened.questions[0].id, selected_option_id="A", response_time_ms=100)],
    )
    second = app.assign("s", request)
    assert set(repository.get(first.id, "s").item_ids).isdisjoint(repository.get(second.id, "s").item_ids)
    assert len(editor.calls) == 1


def test_retry_must_finish_the_mixed_batch_quality_gate():
    first, second = seed_batches()
    editor, critic = Editor(transient=True), _Critic()
    service, _ = _service_with_model(
        _StructuredModel(_quiz_payload(3, Difficulty.BASIC)),
        documents=[_Document(page_content=PCA_EVIDENCE, metadata={})],
        editor=editor,
        critic=critic,
    )
    request = GenerateQuestionsRequest(target_kc_id="pca", count=3)
    with pytest.raises(AssessmentGenerationError) as failed:
        service.generate(
            request, reusable_items=(selected_item(first, origin="a"), selected_item(second, slot=1, origin="b"))
        )
    progress = failed.value.progress
    assert progress.accepted_count == 2
    quiz = service.generate(request, progress=progress)
    assert len(quiz.questions) == 3
    assert any(len(candidates) == 3 and not history for candidates, history in critic.calls)


def test_incompatible_cached_combination_replaces_only_rejected_slot():
    first, second = seed_batches()
    rejection = _critique_payload(1, second.questions[0])
    rejection["distinct_learning_objective"] = False
    critic = _Critic(
        [
            [_critique_payload(0, first.questions[0]), rejection],
            [_critique_payload(0, first.questions[0])],
            [_critique_payload(0, first.questions[0]), _critique_payload(1, first.questions[0])],
        ]
    )
    editor = Editor()
    service, _ = _service_with_model(_StructuredModel(_quiz_payload(2, Difficulty.BASIC)), editor=editor, critic=critic)
    quiz = service.generate(
        GenerateQuestionsRequest(target_kc_id="pca", count=2),
        reusable_items=(selected_item(first, origin="a"), selected_item(second, slot=1, origin="b")),
    )
    assert len(quiz.questions) == 2
    assert quiz.questions[0].stem == first.questions[0].stem
    assert quiz.questions[1].stem != second.questions[0].stem
    assert [slot.slot_index for slot in editor.calls[0].slots] == [1]


def test_missing_slot_and_retry_preserve_frozen_exposure_exclusions():
    from ds_course_agent.assessment.feedback import AssessmentGenerationProgress, QuestionRejectionCode
    from ds_course_agent.assessment.generation_constraints import AssessmentExposureConstraint
    from ds_course_agent.assessment.items import item_identity
    from ds_course_agent.assessment.models import GeneratedQuestion

    first, _ = seed_batches()
    forbidden = GeneratedQuestion.model_validate(_question_payload(1, Difficulty.BASIC))
    exposure = AssessmentExposureConstraint(
        excluded_item_ids=(item_identity(forbidden),), excluded_questions=(forbidden,)
    )

    class RepeatingEditor(Editor):
        def revise_items(self, request):
            self.index = 1 if len(self.calls) < 2 else 2
            return super().revise_items(request)

    editor, critic = RepeatingEditor(), _Critic()
    service, _ = _service_with_model(
        _StructuredModel(_quiz_payload(2, Difficulty.BASIC)),
        documents=[_Document(page_content=PCA_EVIDENCE, metadata={})],
        editor=editor,
        critic=critic,
    )
    request = GenerateQuestionsRequest(target_kc_id="pca", count=2)
    with pytest.raises(AssessmentGenerationError) as failed:
        service.generate(request, reusable_items=(selected_item(first),), exposure=exposure)
    progress = AssessmentGenerationProgress.model_validate_json(failed.value.progress.model_dump_json())
    assert progress.accepted_count == 1
    assert progress.repair_round == 2
    assert progress.pending_slots[0].rejection_codes == (QuestionRejectionCode.RECENT_ITEM_EXPOSURE,)
    assert all(not candidates for candidates, _ in critic.calls)
    # No exclusions supplied in this call: they must come from durable progress.
    quiz = service.generate(request, progress=progress)
    assert len(quiz.questions) == 2
    assert all(item_identity(question) not in exposure.excluded_item_ids for question in quiz.questions)
    assert quiz.repair_round == 3
    assert editor.calls[-1].exposure == exposure


def test_accepted_retry_slot_newly_exposed_before_publication_is_replaced():
    from ds_course_agent.assessment.feedback import AssessmentGenerationProgress
    from ds_course_agent.assessment.generation_constraints import AssessmentExposureConstraint
    from ds_course_agent.assessment.items import item_identity

    first, _ = seed_batches()
    request = GenerateQuestionsRequest(target_kc_id="pca", count=1)
    progress = AssessmentGenerationProgress.completed(request, first)
    exposure = AssessmentExposureConstraint(excluded_item_ids=(item_identity(first.questions[0]),))
    editor = Editor()
    service, _ = _service_with_model(_StructuredModel(_quiz_payload(1, Difficulty.BASIC)), editor=editor)
    # The refresh simulates an assessment appearing during generation/review.
    quiz = service.generate(request, progress=progress, refresh_exposure=lambda: exposure)
    assert len(quiz.questions) == 1
    assert item_identity(quiz.questions[0]) not in exposure.excluded_item_ids
    assert len(editor.calls) == 1


def test_combination_reviewer_unavailable_preserves_gate_and_consumes_lifetime_budget():
    from ds_course_agent.assessment.critic import AssessmentCritiqueError
    from ds_course_agent.assessment.feedback import AssessmentGenerationProgress

    first, second = seed_batches()

    class UnavailableCritic(_Critic):
        def critique_batch(self, request, questions, accepted_questions=()):
            self.calls.append((list(questions), list(accepted_questions)))
            raise AssessmentCritiqueError("offline unavailable")

    critic = UnavailableCritic()
    service, _ = _service_with_model(_StructuredModel(_quiz_payload(2, Difficulty.BASIC)), critic=critic)
    request = GenerateQuestionsRequest(target_kc_id="pca", count=2)
    progress = None
    for attempt in range(1, 6):
        with pytest.raises(AssessmentGenerationError) as failed:
            if progress is None:
                service.generate(
                    request,
                    reusable_items=(selected_item(first, origin="a"), selected_item(second, slot=1, origin="b")),
                )
            else:
                service.generate(request, progress=progress)
        progress = AssessmentGenerationProgress.model_validate_json(failed.value.progress.model_dump_json())
        assert progress.accepted_count == 2
        assert progress.pending_count == 0
        assert progress.batch_review.required
        assert progress.batch_review.certificate is None
        assert progress.repair_round == min(attempt, 4)
        assert progress.retryable is (attempt < 4)
        assert len(critic.calls) == min(attempt, 4)


def test_composition_change_invalidates_a_previous_batch_certificate():
    from ds_course_agent.assessment.feedback import AssessmentGenerationProgress, BatchReviewState
    from ds_course_agent.assessment.generation_constraints import BatchReviewCertificate

    first, second = seed_batches()
    request = GenerateQuestionsRequest(target_kc_id="pca", count=1)
    certificate = BatchReviewCertificate.for_batch(request, first.questions, first.resource_revision.review_policy)
    progress = AssessmentGenerationProgress.completed(request, second).model_copy(
        update={"batch_review": BatchReviewState(required=True, certificate=certificate)}
    )
    critic = _Critic()
    service, _ = _service_with_model(_StructuredModel(_quiz_payload(1, Difficulty.BASIC)), critic=critic)
    quiz = service.generate(request, progress=progress)
    assert quiz.questions[0].stem == second.questions[0].stem
    assert len(critic.calls) == 1
    assert len(critic.calls[0][0]) == 1


def test_only_active_and_last_three_assignments_exclude_older_review_items(tmp_path):
    payloads = [{"title": "PCA练习", "questions": [_question_payload(index, Difficulty.BASIC)]} for index in range(4)]
    model = _StructuredModel(responses=payloads)
    generator, _ = _service_with_model(model, documents=[_Document(page_content=PCA_EVIDENCE, metadata={})])
    repository = AssessmentRepository(tmp_path / "assessment.db")
    app = AssessmentApplicationService(repository, generator)
    request = GenerateQuestionsRequest(target_kc_id="pca", count=1)
    assignments = []
    for _ in range(4):
        assignment = app.assign("s", request)
        opened = app.open(assignment.id, "s")
        app.submit(
            assignment.id,
            "s",
            [AnswerSubmission(question_id=opened.questions[0].id, selected_option_id="A", response_time_ms=100)],
        )
        assignments.append(assignment)
    old_review = app.assign("s", request)
    assert repository.get(old_review.id, "s").item_ids == repository.get(assignments[0].id, "s").item_ids
    assert model.invoke_count == 4


def test_exposure_examples_stay_target_scoped_with_many_other_active_kcs(tmp_path):
    from ds_course_agent.assessment.generator import MAX_AUTHOR_PROMPT_CHARS, AssessmentGenerator
    from ds_course_agent.assessment.models import GeneratedQuiz
    from ds_course_agent.teaching.knowledge_map import NodeType, get_knowledge_map

    class CapturingGenerator:
        def __init__(self):
            self.exposures = []
            self.messages = []

        def generate(self, request, *, exposure, refresh_exposure):
            self.exposures.append(exposure)
            payload = _quiz_payload(1, Difficulty.BASIC)
            payload["questions"][0]["stem"] = f"{request.target_kc_id}课程题目考查什么性质？"
            quiz = GeneratedQuiz.model_validate({**payload, "sources": [{"id": "S1", "text": PCA_EVIDENCE}]})
            self.messages = AssessmentGenerator._build_messages(_task(request), quiz.sources, exposure=exposure)
            return quiz

    generator = CapturingGenerator()
    app = AssessmentApplicationService(AssessmentRepository(tmp_path / "assessment.db"), generator)
    targets = [
        node.canonical_id
        for node in get_knowledge_map().nodes
        if node.node_type is NodeType.KC and node.canonical_id != "pca"
    ][:25]
    for target in targets:
        app.assign("s", GenerateQuestionsRequest(target_kc_id=target, count=1))
    app.assign("s", GenerateQuestionsRequest(target_kc_id="pca", count=1))
    assert len(generator.exposures[-1].excluded_item_ids) == 25
    assert not generator.exposures[-1].excluded_questions
    assert sum(len(message.content) for message in generator.messages) < MAX_AUTHOR_PROMPT_CHARS
    assert all(f"{target}课程题目" not in generator.messages[-1].content for target in targets)


def test_exposure_examples_are_bounded_inside_real_author_and_editor_prompt_caps():
    from ds_course_agent.assessment.feedback import (
        QuestionRejection,
        QuestionRejectionCode,
        QuestionRepairRequest,
        QuestionRepairSlot,
    )
    from ds_course_agent.assessment.generation_constraints import AssessmentExposureConstraint
    from ds_course_agent.assessment.generator import (
        MAX_AUTHOR_PROMPT_CHARS,
        MAX_EXPOSURE_EXAMPLE_CHARS,
        AssessmentGenerator,
    )
    from ds_course_agent.assessment.items import item_identity
    from ds_course_agent.assessment.models import EvidenceSource, GeneratedQuestion

    questions = tuple(
        GeneratedQuestion.model_validate(_question_payload(index, Difficulty.BASIC)) for index in range(100)
    )
    exposure = AssessmentExposureConstraint(
        excluded_item_ids=tuple(map(item_identity, questions)), excluded_questions=questions
    )
    request = GenerateQuestionsRequest(target_kc_id="pca", count=1)
    sources = [EvidenceSource(id="S1", text=PCA_EVIDENCE)]
    plain = AssessmentGenerator._build_messages(_task(request), sources)
    bounded = AssessmentGenerator._build_messages(_task(request), sources, exposure=exposure)
    assert 0 < len(bounded[-1].content) - len(plain[-1].content) <= MAX_EXPOSURE_EXAMPLE_CHARS + 2
    assert len(exposure.excluded_item_ids) == 100
    assert sum(len(message.content) for message in bounded) <= MAX_AUTHOR_PROMPT_CHARS
    repair = QuestionRepairRequest(
        context=_task(request),
        evidence=tuple(sources),
        exposure=exposure,
        slots=(QuestionRepairSlot("pca:slot:0", 0, QuestionRejection((QuestionRejectionCode.RECENT_ITEM_EXPOSURE,))),),
    )
    assert (
        sum(len(message.content) for message in AssessmentGenerator._build_revision_messages(repair))
        <= MAX_AUTHOR_PROMPT_CHARS
    )
    model = _StructuredModel(_quiz_payload(1, Difficulty.BASIC))
    generator = AssessmentGenerator(model=model, editor_model=model)
    with pytest.raises(AssessmentGenerationError, match="message construction"):
        generator.generate_candidates(
            _task(request),
            [EvidenceSource(id=f"S{index}", text="教材" * 12000) for index in range(3)],
            exposure=exposure,
        )
    huge_slot = QuestionRepairSlot(
        "pca:slot:0",
        0,
        QuestionRejection((QuestionRejectionCode.RECENT_ITEM_EXPOSURE,), detail="说明" * MAX_AUTHOR_PROMPT_CHARS),
    )
    with pytest.raises(AssessmentGenerationError, match="message construction"):
        generator.revise_items(
            QuestionRepairRequest(
                context=_task(request), evidence=tuple(sources), slots=(huge_slot,), exposure=exposure
            )
        )
    assert model.invoke_count == 0
