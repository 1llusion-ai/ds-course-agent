"""On-demand content accumulation, independent assignments, and strict reuse."""

import pytest

from ds_course_agent.assessment.application import AssessmentApplicationService
from ds_course_agent.assessment.generator import AssessmentGenerationError, AssessmentGenerator
from ds_course_agent.assessment.items import (
    ReviewedItem,
    ReviewedItemConflictError,
    ReviewedItemRepository,
    SelectedItem,
    item_identity,
)
from ds_course_agent.assessment.models import (
    Difficulty,
    GeneratedQuestion,
    GenerateQuestionsRequest,
)
from ds_course_agent.assessment.repository import AssessmentRepository
from ds_course_agent.assessment.service import AssessmentService, NoAssessmentEvidence
from ds_course_agent.assessment.verifier import EvidenceVerificationVerdict
from ds_course_agent.assessment.versioning import assessment_resource_revision
from tests.test_assessment_core import (
    PCA_EVIDENCE,
    _Critic,
    _critique_payload,
    _Document,
    _question_payload,
    _quiz_payload,
    _Retriever,
    _service_with_model,
    _StructuredModel,
    _Verifier,
)


def selected_item(quiz, index=0, *, slot=0, origin="batch", target="pca"):
    question = quiz.questions[index]
    return SelectedItem(
        slot_index=slot,
        item=ReviewedItem(
            item_id=item_identity(question),
            target_kc_id=target,
            question=question,
            sources=tuple(quiz.sources),
            review=quiz.review_certificates[index],
            resource_revision=quiz.resource_revision,
            origin_batch=origin,
        ),
    )


def test_content_identity_ignores_order_and_explanation_but_preserves_math():
    question = GeneratedQuestion.model_validate(_question_payload(0, Difficulty.BASIC))
    permuted = question.model_copy(update={"options": list(reversed(question.options)), "explanation": "不同解析"})
    assert item_identity(question) == item_identity(permuted)
    for left, right in (("x²", "x2"), ("x+2", "x-2"), ("r=0.2", "r=0.3"), ("不是", "是"), ("x!", "x"), ("X", "x")):
        assert item_identity(question.model_copy(update={"stem": f"判断{left}的结果？"})) != item_identity(
            question.model_copy(update={"stem": f"判断{right}的结果？"})
        )


def test_reviewed_content_is_shared_but_active_assignments_are_student_scoped(tmp_path):
    model = _StructuredModel(_quiz_payload(2, Difficulty.BASIC))
    generator, retriever = _service_with_model(model, documents=[_Document(page_content=PCA_EVIDENCE, metadata={})])
    repository = AssessmentRepository(tmp_path / "assessment.db")
    service = AssessmentApplicationService(repository, generator)
    request = GenerateQuestionsRequest(target_kc_id="pca", count=2)
    first = service.assign("first", request, session_id="s1")
    assert service.assign("first", request, session_id="s2").id == first.id
    second = service.assign("second", request, session_id="s2")
    assert first.id != second.id
    assert model.invoke_count == 1
    assert len(retriever.calls) == 1
    a, b = repository.get(first.id, "first"), repository.get(second.id, "second")
    assert a.question_ids != b.question_ids
    assert set(a.item_ids) == set(b.item_ids)
    assert b.quiz.review_certificates
    assert repository.get(first.id, "second") is None
    assets = ReviewedItemRepository(repository.path)
    revision = assessment_resource_revision("data-science-intro")
    assert assets.select(request, revision)
    assert not assets.select(request, revision.model_copy(update={"graph_digest": "new"}))
    assert not assets.select(request, assessment_resource_revision("digital-literacy"))
    assert not assets.select(request.model_copy(update={"difficulty": Difficulty.ADVANCED}), revision)
    assert not assets.select(request, revision, excluded_item_ids=a.item_ids)


def test_old_evidence_policy_assets_are_not_selected_for_current_resources(tmp_path):
    model = _StructuredModel(_quiz_payload(2, Difficulty.BASIC))
    generator, _ = _service_with_model(model, documents=[_Document(page_content=PCA_EVIDENCE, metadata={})])
    request = GenerateQuestionsRequest(target_kc_id="pca", count=2)
    quiz = generator.generate(request)
    current = quiz.resource_revision
    legacy = current.model_copy(update={"evidence_policy": "target-coverage/2"})
    assets = ReviewedItemRepository(tmp_path / "assessment.db")
    assets.accumulate(request, quiz.model_copy(update={"resource_revision": legacy}))
    assert assets.select(request, legacy)
    assert not assets.select(request, current)


def test_missing_slot_only_is_generated_and_reviewed(tmp_path):
    class Editor:
        def __init__(self):
            self.requests = []

        def revise_items(self, request):
            from ds_course_agent.assessment.feedback import QuestionRepairBatch

            self.requests.append(request)
            return QuestionRepairBatch.model_validate(
                {
                    "revisions": [
                        {"slot_id": request.slots[0].slot_id, "question": _question_payload(2, Difficulty.BASIC)}
                    ]
                }
            )

    editor = Editor()
    model = _StructuredModel(_quiz_payload(1, Difficulty.BASIC))
    generator, _ = _service_with_model(
        model, documents=[_Document(page_content=PCA_EVIDENCE, metadata={})], editor=editor
    )
    repository = AssessmentRepository(tmp_path / "assessment.db")
    app = AssessmentApplicationService(repository, generator)
    app.assign("first", GenerateQuestionsRequest(target_kc_id="pca", count=1))
    result = app.assign("second", GenerateQuestionsRequest(target_kc_id="pca", count=2))
    assert result.question_count == 2
    assert model.invoke_count == 1
    assert len(editor.requests) == 1
    assert [slot.slot_index for slot in editor.requests[0].slots] == [1]
    record = repository.get(result.id, "second")
    assert len(record.quiz.review_certificates) == 2


def test_same_surface_with_different_verified_answer_is_quarantined(tmp_path):
    model = _StructuredModel(_quiz_payload(1, Difficulty.BASIC))
    generator, _ = _service_with_model(model, documents=[_Document(page_content=PCA_EVIDENCE, metadata={})])
    request = GenerateQuestionsRequest(target_kc_id="pca", count=1)
    quiz = generator.generate(request)
    assets = ReviewedItemRepository(tmp_path / "assessment.db")
    assets.accumulate(request, quiz)
    conflicting = quiz.model_copy(
        update={"questions": [quiz.questions[0].model_copy(update={"correct_option_id": "B"})]}
    )
    with pytest.raises(ReviewedItemConflictError):
        assets.accumulate(request, conflicting)
    assert not assets.select(request, quiz.resource_revision)


def test_full_combination_name_cannot_fake_correct_answer_member_coverage():
    request = GenerateQuestionsRequest(target_kc_id="dl_5_8_6_1", count=2)
    payload = _quiz_payload(2, Difficulty.BASIC)
    for index, item in enumerate(payload["questions"]):
        item["stem"] = f"相关系数与最小二乘回归：如何解释相关系数的第{index}种情形？"
    model = _StructuredModel(payload)
    evidence = "相关系数的正负性反映变量变化的方向，其绝对值大小反映线性相关程度。最小二乘法通过最小化残差平方和估计线性回归参数。"
    verifier = _Verifier(
        verdict_batches=[
            [
                {
                    "question_index": index,
                    "supported_options": [{"option_id": "A", "excerpt_id": "E1"}],
                    "on_topic": True,
                    "answer_explanation": "相关系数教材说明支持这个结论。",
                }
                for index in range(2)
            ]
        ]
    )
    service = AssessmentService(
        retriever=_Retriever([_Document(page_content=evidence, metadata={})]),
        generator=AssessmentGenerator(model=model, editor_model=model),
        verifier=verifier,
        critic=_Critic(),
        course_id="digital-literacy",
    )
    with pytest.raises(NoAssessmentEvidence, match="correct-answer excerpts"):
        service.generate(request)


def test_oversized_reuse_falls_back_to_normal_bounded_generation():
    request = GenerateQuestionsRequest(target_kc_id="pca", count=1)
    seed, _ = _service_with_model(
        _StructuredModel(_quiz_payload(1, Difficulty.BASIC)),
        documents=[_Document(page_content=PCA_EVIDENCE, metadata={})],
    )
    selected = selected_item(seed.generate(request))
    source = selected.item.sources[0]
    oversized = selected.model_copy(
        update={
            "item": selected.item.model_copy(
                update={"sources": (source.model_copy(update={"text": source.text + "补充。" * 1000}),)}
            )
        }
    )
    model = _StructuredModel(_quiz_payload(1, Difficulty.BASIC))
    service, retriever = _service_with_model(
        model, documents=[_Document(page_content=PCA_EVIDENCE, metadata={})], context_max_chars=1000
    )
    quiz = service.generate(request, reusable_items=(oversized,))
    assert len(quiz.questions) == 1
    assert model.invoke_count == 1
    assert len(retriever.calls) == 1
    assert sum(len(source.text) for source in quiz.sources) <= 1000


def test_mixed_reviewed_batches_exhausted_repair_retains_good_slots():
    request = GenerateQuestionsRequest(target_kc_id="pca", count=1)
    payload = _quiz_payload(1, Difficulty.BASIC)
    other_payload = {**payload, "questions": [_question_payload(2, Difficulty.BASIC)]}
    seed, _ = _service_with_model(
        _StructuredModel(responses=[payload, other_payload]),
        documents=[_Document(page_content=PCA_EVIDENCE, metadata={})],
    )
    first, second = seed.generate(request), seed.generate(request)
    rejection = _critique_payload(1, second.questions[0])
    rejection["distinct_learning_objective"] = False
    critic = _Critic([[_critique_payload(0, first.questions[0]), rejection]])
    model = _StructuredModel(_quiz_payload(2, Difficulty.BASIC))
    service, retriever = _service_with_model(model, critic=critic)
    with pytest.raises(AssessmentGenerationError, match="semantic_duplicate") as failed:
        service.generate(
            request.model_copy(update={"count": 2}),
            reusable_items=(selected_item(first, origin="first"), selected_item(second, slot=1, origin="second")),
        )
    assert len(critic.calls) == 1
    assert not retriever.calls
    assert model.invoke_count == 2
    assert failed.value.progress.accepted_count == 1
    assert failed.value.progress.pending_slots[0].slot_index == 1
    assert failed.value.progress.batch_review.required
    assert failed.value.progress.batch_review.certificate is None


def test_incomplete_composite_cache_generates_only_missing_member():
    target = "dl_5_8_6_1"
    request = GenerateQuestionsRequest(target_kc_id=target, count=2)
    payload = _quiz_payload(2, Difficulty.BASIC)
    payload["questions"][0]["stem"] = "相关系数的正负反映什么性质？"
    payload["questions"][1]["stem"] = "最小二乘法通过最小化什么来估计参数？"
    evidence = "相关系数的正负性反映变量变化的方向，其绝对值大小反映线性相关程度。最小二乘法通过最小化残差平方和估计线性回归参数。"

    class MemberVerifier(_Verifier):
        def verify(self, request, questions, catalog):
            self.calls.append(list(questions))
            return tuple(
                EvidenceVerificationVerdict.model_validate(
                    {
                        "question_index": index,
                        "supported_options": [
                            {
                                "option_id": "A",
                                "excerpt_id": next(
                                    excerpt.id
                                    for excerpt in catalog.excerpts
                                    if ("最小二乘法" in excerpt.text) == ("最小二乘法" in question.stem)
                                ),
                            }
                        ],
                        "on_topic": True,
                        "answer_explanation": "教材分别说明相关系数的方向和最小二乘法的估计目标。",
                    }
                )
                for index, question in enumerate(questions)
            )

    class Editor:
        def __init__(self):
            self.requests = []

        def revise_items(self, request):
            from ds_course_agent.assessment.feedback import QuestionRepairBatch

            self.requests.append(request)
            return QuestionRepairBatch.model_validate(
                {"revisions": [{"slot_id": request.slots[0].slot_id, "question": payload["questions"][1]}]}
            )

    verifier, critic, editor = MemberVerifier(), _Critic(), Editor()
    retriever = _Retriever([_Document(page_content=evidence, metadata={})])
    model = _StructuredModel(payload)
    service = AssessmentService(
        retriever=retriever,
        generator=AssessmentGenerator(model=model, editor_model=model),
        verifier=verifier,
        critic=critic,
        editor=editor,
        course_id="digital-literacy",
    )
    # A valid original batch demonstrates real E1 + E2 correct-answer coverage.
    seed = service.generate(request)
    first = selected_item(seed, target=target)
    # A second certified correlation item can originate in another valid batch;
    # its semantic support is still E1, despite having a distinct surface identity.
    other_payload = {**payload, "questions": [dict(payload["questions"][0]), payload["questions"][1]]}
    other_payload["questions"][0]["stem"] = "相关系数的绝对值反映什么性质？"
    model.responses.append(other_payload)
    other = service.generate(request)
    second = selected_item(other, slot=1, target=target)
    result = service.generate(request, reusable_items=(first, second))
    assert len(result.questions) == 2
    assert model.invoke_count == 2
    assert len(editor.requests) == 1
    assert [slot.slot_index for slot in editor.requests[0].slots] == [1]
    assert "least_squares_regression" in editor.requests[0].slots[0].rejection.detail
    assert any("最小二乘法" in support.text for review in result.review_certificates for support in review.supports)
