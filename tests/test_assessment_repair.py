"""Regression coverage for actionable repair and observable rejection gates."""

from __future__ import annotations

import logging

import pytest

from ds_course_agent.assessment.critic import ItemCritique
from ds_course_agent.assessment.feedback import QuestionRejectionCode
from ds_course_agent.assessment.generator import (
    AssessmentGenerationError,
    AssessmentModelCallError,
)
from ds_course_agent.assessment.models import (
    Difficulty,
    GeneratedQuestion,
    GenerateQuestionsRequest,
)
from ds_course_agent.assessment.service import AssessmentService
from tests.test_assessment_core import (
    PCA_EVIDENCE,
    _Critic,
    _critique_payload,
    _Document,
    _question_payload,
    _quiz_payload,
    _service_with_model,
    _StructuredModel,
    _Verifier,
)


@pytest.mark.parametrize(
    ("difficulty", "operation", "accepted"),
    [
        (Difficulty.BASIC, "recall", True),
        (Difficulty.BASIC, "application", True),
        (Difficulty.INTERMEDIATE, "recall", False),
        (Difficulty.INTERMEDIATE, "application", True),
        (Difficulty.ADVANCED, "recall", False),
        (Difficulty.ADVANCED, "application", False),
        (Difficulty.ADVANCED, "analysis", True),
    ],
)
def test_requested_label_cannot_override_observed_cognitive_operation(
    difficulty: Difficulty, operation: str, accepted: bool
) -> None:
    question = GeneratedQuestion.model_validate(_question_payload(0, difficulty))
    payload = _critique_payload(0, question)
    payload["cognitive_operation"] = operation
    codes = AssessmentService._critique_rejection_codes(question, ItemCritique.model_validate(payload))
    assert (QuestionRejectionCode.DIFFICULTY_MISMATCH not in codes) is accepted


def test_repair_preserves_accepted_items_and_can_fix_options_without_changing_stem() -> None:
    initial = _quiz_payload(2, Difficulty.BASIC)
    repair = _quiz_payload(1, Difficulty.BASIC)
    repair["questions"][0] = _question_payload(1, Difficulty.BASIC)
    repair["questions"][0]["options"][1]["text"] = "把样本数量减少误认为特征维度减少"
    first, rejected = [GeneratedQuestion.model_validate(item) for item in initial["questions"]]
    fixed = GeneratedQuestion.model_validate(repair["questions"][0])
    verdict = _critique_payload(0, rejected)
    verdict["option_critiques"][1].update(
        assessment="distractor",
        same_type_and_granularity=False,
        reason="OPTION_B_FEEDBACK: replace sample count with feature-space confusion.",
    )
    verdict["cognitive_operation"] = "analysis"
    verdict["reason"] = "ITEM_FEEDBACK: test the distinction between rows and features."
    critic = _Critic(
        [
            [_critique_payload(0, first)],
            [verdict],
            [_critique_payload(0, fixed)],
        ]
    )
    model = _StructuredModel(responses=[initial, repair])
    service, _ = _service_with_model(model, critic=critic, documents=[_Document(PCA_EVIDENCE)])

    quiz = service.generate(GenerateQuestionsRequest(target_kc_id="pca", count=2))

    assert quiz.questions == [first, fixed]
    assert rejected.stem == fixed.stem
    assert model.invoke_count == 2
    prompt = model.message_batches[1][-1].content
    assert "题目数量：1" in prompt
    assert "已通过题目" in prompt
    assert first.stem in prompt
    assert rejected.options[1].text in prompt
    assert "OPTION_B_FEEDBACK" in prompt
    assert "ITEM_FEEDBACK" in prompt
    assert "implausible_distractors" in prompt
    assert "difficulty_mismatch" in prompt
    assert critic.calls[1][1] == [first]


def test_provider_failure_logs_stage_and_cause_without_secrets_or_repair(
    caplog: pytest.LogCaptureFixture,
) -> None:
    model = _StructuredModel(error=TimeoutError("provider token=DO_NOT_LOG_CREDENTIAL"))
    service, _ = _service_with_model(model, documents=[_Document(PCA_EVIDENCE)])
    caplog.set_level(logging.INFO)

    with pytest.raises(AssessmentModelCallError):
        service.generate(GenerateQuestionsRequest(target_kc_id="pca", count=1))

    assert model.invoke_count == 1
    assert "stage=generation" in caplog.text
    assert "error_types=AssessmentModelCallError,TimeoutError" in caplog.text
    assert "DO_NOT_LOG_CREDENTIAL" not in caplog.text
    assert PCA_EVIDENCE not in caplog.text
    records = [r.message for r in caplog.records if r.name.endswith("assessment.diagnostics")]
    request_ids = {text.split("request_id=", 1)[1].split()[0] for text in records}
    assert len(request_ids) == 1


def test_published_explanation_uses_the_blind_evidence_rationale() -> None:
    draft = _quiz_payload(1, Difficulty.BASIC)
    draft["questions"][0]["explanation"] = "UNVERIFIED_AUTHOR_CLAIM"
    rationale = "PCA 保留主要方差方向以降低特征维度，不以类别标签作为优化目标。"
    verifier = _Verifier(
        [
            [
                {
                    "question_index": 0,
                    "supported_options": [{"option_id": "A", "excerpt_id": "E1"}],
                    "on_topic": True,
                    "answer_explanation": rationale,
                }
            ]
        ]
    )
    model = _StructuredModel(draft)
    service, _ = _service_with_model(model, verifier=verifier, documents=[_Document(PCA_EVIDENCE)])

    quiz = service.generate(GenerateQuestionsRequest(target_kc_id="pca", count=1))

    assert quiz.questions[0].explanation == rationale
    assert "UNVERIFIED_AUTHOR_CLAIM" not in quiz.model_dump_json()
    assert model.invoke_count == 1


def test_published_explanation_does_not_expose_internal_evidence_ids() -> None:
    draft = _quiz_payload(1, Difficulty.BASIC)
    verifier = _Verifier(
        [
            [
                {
                    "question_index": 0,
                    "supported_options": [{"option_id": "A", "excerpt_id": "E2"}],
                    "on_topic": True,
                    "answer_explanation": "根据教材证据[E1]和[E2]，正确选项成立。",
                }
            ]
        ]
    )
    sources = [
        _Document("PCA 是主成分分析。\n" + PCA_EVIDENCE),
    ]
    question = GeneratedQuestion.model_validate(draft["questions"][0])
    question = question.model_copy(update={"source_ids": ["S1"]})
    draft["questions"][0] = question.model_dump(mode="json")
    service, _ = _service_with_model(_StructuredModel(draft), verifier=verifier, documents=sources)

    quiz = service.generate(GenerateQuestionsRequest(target_kc_id="pca", count=1))

    assert quiz.questions[0].explanation == "根据教材内容，正确选项成立。"


def test_repeated_quality_rejection_logs_codes_and_stops_at_one_repair(
    caplog: pytest.LogCaptureFixture,
) -> None:
    draft = _quiz_payload(1, Difficulty.BASIC)
    question = GeneratedQuestion.model_validate(draft["questions"][0])
    critique = _critique_payload(0, question)
    critique["option_critiques"][1].update(assessment="distractor", same_type_and_granularity=False)
    critique["reason"] = "PRIVATE_REVIEW_CONTENT"
    model = _StructuredModel(draft)
    service, _ = _service_with_model(model, critic=_Critic([[critique]]), documents=[_Document(PCA_EVIDENCE)])
    caplog.set_level(logging.INFO)

    with pytest.raises(
        AssessmentGenerationError,
        match="repair budget exhausted: implausible_distractors",
    ):
        service.generate(GenerateQuestionsRequest(target_kc_id="pca", count=1))

    assert model.invoke_count == 2
    assert caplog.text.count("stage=acceptance") == 2
    assert "rejection_codes=implausible_distractors" in caplog.text
    assert "error_types=AssessmentGenerationError" in caplog.text
    assert "PRIVATE_REVIEW_CONTENT" not in caplog.text


def test_critic_reviews_one_item_per_call_and_excludes_rejected_items_from_context() -> None:
    draft = _quiz_payload(3, Difficulty.BASIC)
    questions = [GeneratedQuestion.model_validate(item) for item in draft["questions"]]
    rejected = _critique_payload(0, questions[1])
    rejected["option_critiques"][1].update(assessment="distractor", same_type_and_granularity=False)
    repair = _quiz_payload(1, Difficulty.BASIC)
    repair["questions"][0] = _question_payload(4, Difficulty.BASIC)
    fixed = GeneratedQuestion.model_validate(repair["questions"][0])
    critic = _Critic(
        [
            [_critique_payload(0, questions[0])],
            [rejected],
            [_critique_payload(0, questions[2])],
            [_critique_payload(0, fixed)],
        ]
    )
    model = _StructuredModel(responses=[draft, repair])
    evidence = PCA_EVIDENCE + "PCA 在降维过程中用较少的新特征表示原始高维特征之间的大部分变异信息。"
    service, _ = _service_with_model(model, critic=critic, documents=[_Document(evidence)])

    quiz = service.generate(GenerateQuestionsRequest(target_kc_id="pca", count=3))

    assert quiz.questions == [questions[0], questions[2], fixed]
    assert [len(batch) for batch, _ in critic.calls] == [1, 1, 1, 1]
    assert critic.calls[1][1] == [questions[0]]
    assert critic.calls[2][1] == [questions[0]]
    assert critic.calls[3][1] == [questions[0], questions[2]]
    assert model.invoke_count == 2
