"""Contracts and boundary tests for the assessment core MVP."""

from __future__ import annotations

import ast
import sys
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from pydantic import ValidationError

import ds_course_agent.assessment.service as assessment_service_module
from ds_course_agent.assessment.critic import (
    AssessmentCritiqueError,
    AssessmentQualityCritic,
    ItemCritique,
)
from ds_course_agent.assessment.evidence import resolve_target
from ds_course_agent.assessment.generator import (
    AssessmentGenerationError,
    AssessmentGenerator,
)
from ds_course_agent.assessment.models import (
    Difficulty,
    EvidenceSource,
    GeneratedQuestion,
    GenerateQuestionsRequest,
    QuestionOption,
)
from ds_course_agent.assessment.service import (
    AssessmentService,
    AssessmentUnavailableError,
    NoAssessmentEvidence,
    get_assessment_service,
)
from ds_course_agent.assessment.verifier import (
    AssessmentEvidenceVerifier,
    AssessmentVerificationError,
    EvidenceExcerptCatalog,
    EvidenceVerificationVerdict,
)
from tests.subprocess_utils import run_python_script

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "ds_course_agent" / "assessment"
PCA_EVIDENCE = (
    "PCA 通过将原始数据投影到主要变化方向来减少特征维度并保留数据的主要信息。"
    "PCA 的各个主成分之间相互正交，通常按照能够解释的方差大小进行排序。"
)


@dataclass
class _Document:
    page_content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class _RetrievalResult:
    documents: list[_Document]


class _Retriever:
    def __init__(self, documents: list[_Document] | None = None, error: Exception | None = None) -> None:
        self.documents = documents or []
        self.error = error
        self.calls: list[tuple[str, int | None]] = []

    def retrieve(self, question: str, top_k: int | None = None) -> _RetrievalResult:
        self.calls.append((question, top_k))
        if self.error is not None:
            raise self.error
        return _RetrievalResult(documents=self.documents)


class _StructuredRunnable:
    def __init__(self, owner: _StructuredModel) -> None:
        self._owner = owner

    def invoke(self, messages: list[Any]) -> Any:
        self._owner.messages = messages
        self._owner.message_batches.append(messages)
        call_index = self._owner.invoke_count
        self._owner.invoke_count += 1
        if self._owner.error is not None:
            raise self._owner.error
        outcome = self._owner.responses[min(call_index, len(self._owner.responses) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _StructuredModel:
    def __init__(
        self,
        response: Any = None,
        error: Exception | None = None,
        *,
        responses: list[Any] | None = None,
    ) -> None:
        self.responses = list(responses) if responses is not None else [response]
        if not self.responses:
            raise ValueError("responses must not be empty")
        self.error = error
        self.schema: type[Any] | None = None
        self.structured_kwargs: dict[str, Any] = {}
        self.messages: list[Any] | None = None
        self.message_batches: list[list[Any]] = []
        self.invoke_count = 0
        self.direct_invoke_called = False

    def with_structured_output(self, schema: type[Any], **kwargs: Any) -> _StructuredRunnable:
        self.schema = schema
        self.structured_kwargs = kwargs
        return _StructuredRunnable(self)

    def invoke(self, messages: list[Any]) -> Any:
        self.direct_invoke_called = True
        raise AssertionError("the structured model path must be used")


class _Verifier:
    def __init__(self, verdict_batches: list[list[dict[str, Any]]] | None = None) -> None:
        self.verdict_batches = verdict_batches
        self.calls: list[list[GeneratedQuestion]] = []
        self.catalogs: list[EvidenceExcerptCatalog] = []

    def verify(
        self,
        request: GenerateQuestionsRequest,
        questions: Sequence[GeneratedQuestion],
        catalog: EvidenceExcerptCatalog,
    ) -> tuple[EvidenceVerificationVerdict, ...]:
        del request
        self.calls.append(list(questions))
        self.catalogs.append(catalog)
        call_index = len(self.calls) - 1
        if self.verdict_batches is None:
            payloads = [
                {
                    "question_index": index,
                    "supported_options": [
                        {
                            "option_id": question.correct_option_id,
                            "excerpt_id": "E1",
                        }
                    ],
                    "on_topic": True,
                    "answer_explanation": "教材说明 PCA 通过保留主要变化方向实现降维。",
                }
                for index, question in enumerate(questions)
            ]
        else:
            payloads = self.verdict_batches[min(call_index, len(self.verdict_batches) - 1)]
        return tuple(EvidenceVerificationVerdict.model_validate(payload) for payload in payloads)


class _Critic:
    def __init__(self, critique_batches: list[list[dict[str, Any]]] | None = None) -> None:
        self.critique_batches = critique_batches
        self.calls: list[tuple[list[GeneratedQuestion], list[GeneratedQuestion]]] = []

    def critique(
        self,
        request: GenerateQuestionsRequest,
        questions: Sequence[GeneratedQuestion],
        accepted_questions: Sequence[GeneratedQuestion] = (),
    ) -> tuple[ItemCritique, ...]:
        del request
        self.calls.append((list(questions), list(accepted_questions)))
        call_index = len(self.calls) - 1
        if self.critique_batches is None:
            payloads = [_critique_payload(index, question) for index, question in enumerate(questions)]
        else:
            payloads = self.critique_batches[min(call_index, len(self.critique_batches) - 1)]
        return tuple(ItemCritique.model_validate(payload) for payload in payloads)


def _question_payload(index: int, difficulty: Difficulty, source_ids: list[str] | None = None) -> dict[str, Any]:
    return {
        "stem": f"第 {index + 1} 题：教材中的 PCA 主要用于什么？",
        "options": [
            {"id": "A", "text": f"降低特征维度（题 {index + 1}）"},
            {"id": "B", "text": f"直接增加样本数量（题 {index + 1}）"},
            {"id": "C", "text": f"替代所有数据清洗（题 {index + 1}）"},
            {"id": "D", "text": f"保证模型零误差（题 {index + 1}）"},
        ],
        "correct_option_id": "A",
        "explanation": "教材说明 PCA 通过保留主要变化方向实现降维。",
        "difficulty": difficulty.value,
        "source_ids": source_ids or ["S1"],
    }


def _quiz_payload(count: int, difficulty: Difficulty, source_ids: list[str] | None = None) -> dict[str, Any]:
    return {
        "title": "PCA 教材基础测验",
        "questions": [_question_payload(index, difficulty, source_ids) for index in range(count)],
    }


def _critique_payload(index: int, question: GeneratedQuestion) -> dict[str, Any]:
    return {
        "question_index": index,
        "option_critiques": [
            {
                "option_id": option.id,
                "assessment": "answer" if option.id == question.correct_option_id else "distractor",
                "same_type_and_granularity": True,
                "reason": f"Option {option.id} is structurally plausible.",
            }
            for option in question.options
        ],
        "leakage_signals": [],
        "pedagogical_defects": [],
        "pedagogically_useful": True,
        "cognitive_operation": {"basic": "recall", "intermediate": "application", "advanced": "analysis"}[
            question.difficulty.value
        ],
        "distinct_learning_objective": True,
        "learning_objective": f"objective-{index}",
        "reason": "The item passed the pedagogical critique.",
    }


def _service_with_model(
    model: _StructuredModel,
    *,
    documents: list[_Document] | None = None,
    context_max_chars: int | None = None,
    verifier: _Verifier | None = None,
    critic: _Critic | None = None,
) -> tuple[AssessmentService, _Retriever]:
    retriever = _Retriever(documents)
    service = AssessmentService(
        retriever=retriever,
        generator=AssessmentGenerator(model=model),
        verifier=verifier or _Verifier(),
        critic=critic or _Critic(),
        context_max_chars=context_max_chars,
    )
    return service, retriever


def test_request_contract_trims_kc_id_and_enforces_strict_bounded_count() -> None:
    request = GenerateQuestionsRequest(target_kc_id="  pca  ")

    assert request.target_kc_id == "pca"
    assert request.count == 5
    assert request.difficulty is Difficulty.BASIC
    assert request.question_type.value == "single_choice"

    for invalid_count in (0, 11, 2.0, "2", True):
        with pytest.raises(ValidationError):
            GenerateQuestionsRequest(target_kc_id="pca", count=invalid_count)
    for invalid_kc_id in ("   ", "x" * 101, 12):
        with pytest.raises(ValidationError):
            GenerateQuestionsRequest(target_kc_id=invalid_kc_id)

    for invalid_rounds in (-1, 2, 1.0, True):
        with pytest.raises(ValueError):
            AssessmentService(repair_rounds=invalid_rounds)


def test_question_contract_requires_four_distinct_options_and_matching_answer() -> None:
    valid = _question_payload(0, Difficulty.BASIC)
    valid["options"][3]["text"] = valid["options"][0]["text"]
    with pytest.raises(ValidationError):
        GeneratedQuestion.model_validate(valid)

    invalid_answer = _question_payload(0, Difficulty.BASIC)
    invalid_answer["correct_option_id"] = "D"
    invalid_answer["options"][3]["id"] = "C"
    with pytest.raises(ValidationError):
        GeneratedQuestion.model_validate(invalid_answer)

    with pytest.raises(ValidationError):
        EvidenceSource(id="S1", text="教材片段", source=" ")
    with pytest.raises(ValidationError):
        QuestionOption(id="A", text=" " * 3)

    short_stem = _question_payload(0, Difficulty.BASIC)
    short_stem["stem"] = "分组聚合"
    with pytest.raises(ValidationError):
        GeneratedQuestion.model_validate(short_stem)


@pytest.mark.parametrize(
    ("field", "text"),
    [
        ("stem", "代码 squid.groupby("),
        ("stem", "比较 loc[2) 的行为"),
        ("option", "使用字典 {key: value"),
        ("option", "教材【示例"),
        ("explanation", "参见《数据科学导论"),
        ("explanation", "先执行（分组】再聚合"),
    ],
)
def test_question_contract_rejects_unbalanced_delimiters(field: str, text: str) -> None:
    payload = _question_payload(0, Difficulty.BASIC)
    if field == "option":
        payload["options"][0]["text"] = text
    else:
        payload[field] = text

    with pytest.raises(ValidationError, match="unbalanced delimiters"):
        GeneratedQuestion.model_validate(payload)


def test_question_contract_accepts_nested_balanced_delimiters() -> None:
    payload = _question_payload(0, Difficulty.BASIC)
    payload["stem"] = '教材《分组聚合》中，squid.groupby(["species"]) 的作用是什么？'
    payload["options"][0]["text"] = "按【物种（species）】分组"
    payload["explanation"] = 'groupby(["species"]) 使用列表中的字段进行分组。'

    question = GeneratedQuestion.model_validate(payload)

    assert question.stem == payload["stem"]


def test_service_generates_exact_grounded_quiz_with_server_owned_sources() -> None:
    model = _StructuredModel(_quiz_payload(2, Difficulty.INTERMEDIATE, ["S1"]))
    service, retriever = _service_with_model(
        model,
        documents=[
            _Document(
                page_content=PCA_EVIDENCE,
                metadata={"source": "chapter-7.pdf", "book_page": 42},
            )
        ],
    )

    quiz = service.generate(
        GenerateQuestionsRequest(target_kc_id="  pca  ", count=2, difficulty=Difficulty.INTERMEDIATE)
    )

    assert retriever.calls == [(resolve_target(GenerateQuestionsRequest(target_kc_id="pca")).query, 12)]
    assert model.schema is not None and model.schema.__name__ == "QuizDraft"
    assert model.structured_kwargs == {"method": "function_calling"}
    assert model.invoke_count == 1
    assert model.direct_invoke_called is False
    assert len(quiz.questions) == 2
    assert all(question.difficulty is Difficulty.INTERMEDIATE for question in quiz.questions)
    assert quiz.sources == [
        EvidenceSource(
            id="S1",
            text=PCA_EVIDENCE.replace("。PCA", "。\nPCA"),
            source="chapter-7.pdf",
            page=42,
        )
    ]

    assert model.messages is not None
    system_prompt = model.messages[0].content
    prompt = model.messages[-1].content
    assert "不能只写主题名称" in system_prompt
    assert "字符串参数统一使用单引号" in system_prompt
    assert "[S1]" in prompt
    assert quiz.sources[0].text in prompt


def test_service_binds_returned_sources_to_the_exact_bounded_model_evidence() -> None:
    model = _StructuredModel(_quiz_payload(1, Difficulty.BASIC, ["S1"]))
    service, _ = _service_with_model(
        model,
        documents=[
            _Document(page_content=PCA_EVIDENCE, metadata={"source": "one.pdf", "page": 1}),
            _Document(page_content=PCA_EVIDENCE, metadata={"source": "two.pdf", "page": 2}),
        ],
        context_max_chars=45,
    )

    quiz = service.generate(GenerateQuestionsRequest(target_kc_id="pca", count=1))

    assert [source.id for source in quiz.sources] == ["S1"]
    assert quiz.sources[0].text == PCA_EVIDENCE.split("。")[0] + "。"
    assert sum(len(source.text) for source in quiz.sources) <= 45
    assert model.messages is not None
    prompt = model.messages[-1].content
    for source in quiz.sources:
        assert f"[{source.id}]" in prompt
        assert source.text in prompt


def test_no_evidence_prevents_any_model_call() -> None:
    model = _StructuredModel(_quiz_payload(1, Difficulty.BASIC))
    service, retriever = _service_with_model(model, documents=[])

    with pytest.raises(NoAssessmentEvidence):
        service.generate(GenerateQuestionsRequest(target_kc_id="pca", count=1))

    assert retriever.calls == [(resolve_target(GenerateQuestionsRequest(target_kc_id="pca")).query, 12)]
    assert model.schema is None
    assert model.invoke_count == 0


def test_service_repairs_only_rejected_questions_and_preserves_accepted_questions() -> None:
    initial = _quiz_payload(2, Difficulty.BASIC)
    initial["questions"][1]["stem"] = "如何使用 sort_values 对结果进行排序？"
    repair = _quiz_payload(1, Difficulty.BASIC)
    repair["questions"][0] = _question_payload(2, Difficulty.BASIC)
    model = _StructuredModel(responses=[initial, repair])
    service, _ = _service_with_model(
        model,
        documents=[_Document(page_content=PCA_EVIDENCE, metadata={})],
    )

    quiz = service.generate(GenerateQuestionsRequest(target_kc_id="pca", count=2))

    assert model.invoke_count == 2
    assert quiz.questions[0] == GeneratedQuestion.model_validate(initial["questions"][0])
    assert quiz.questions[1] == GeneratedQuestion.model_validate(repair["questions"][0])
    repair_prompt = model.message_batches[1][-1].content
    assert "题目数量：1" in repair_prompt
    assert initial["questions"][0]["stem"] in repair_prompt
    assert "off_topic" in repair_prompt


def test_evidence_verifier_rejects_ambiguous_question_and_repairs_only_that_slot() -> None:
    initial = _quiz_payload(2, Difficulty.BASIC)
    repair = _quiz_payload(1, Difficulty.BASIC)
    repair["questions"][0] = _question_payload(3, Difficulty.BASIC)
    verifier = _Verifier(
        verdict_batches=[
            [
                {
                    "question_index": 0,
                    "supported_options": [{"option_id": "A", "excerpt_id": "E1"}],
                    "on_topic": True,
                    "answer_explanation": "The answer is uniquely supported.",
                },
                {
                    "question_index": 1,
                    "supported_options": [
                        {"option_id": "A", "excerpt_id": "E1"},
                        {"option_id": "B", "excerpt_id": "E1"},
                    ],
                    "on_topic": True,
                    "answer_explanation": "More than one option is supported by the evidence.",
                },
            ],
            [
                {
                    "question_index": 0,
                    "supported_options": [{"option_id": "A", "excerpt_id": "E1"}],
                    "on_topic": True,
                    "answer_explanation": "The repaired item has one supported answer.",
                }
            ],
        ]
    )
    model = _StructuredModel(responses=[initial, repair])
    service, _ = _service_with_model(
        model,
        verifier=verifier,
        documents=[_Document(page_content=PCA_EVIDENCE, metadata={})],
    )

    quiz = service.generate(GenerateQuestionsRequest(target_kc_id="pca", count=2))

    assert model.invoke_count == 2
    assert quiz.questions[0] == GeneratedQuestion.model_validate(initial["questions"][0]).model_copy(
        update={"explanation": "The answer is uniquely supported."}
    )
    assert quiz.questions[1] == GeneratedQuestion.model_validate(repair["questions"][0]).model_copy(
        update={"explanation": "The repaired item has one supported answer."}
    )
    assert len(verifier.calls) == 2
    assert verifier.calls[1] == [GeneratedQuestion.model_validate(repair["questions"][0])]
    assert verifier.catalogs[0] is verifier.catalogs[1]
    assert "multiple_correct_answers" in model.message_batches[1][-1].content


@pytest.mark.parametrize(
    ("failure", "expected_rejection"),
    [
        ("ambiguous_answer", "answer_ambiguity"),
        ("answer_leakage", "answer_leakage"),
        ("implausible_distractor", "implausible_distractors"),
        ("low_pedagogical_value", "low_pedagogical_value"),
        ("difficulty_mismatch", "difficulty_mismatch"),
        ("semantic_duplicate", "semantic_duplicate"),
    ],
)
def test_item_quality_rejections_trigger_one_bounded_repair(
    failure: str,
    expected_rejection: str,
) -> None:
    initial = _quiz_payload(1, Difficulty.BASIC)
    repair = _quiz_payload(1, Difficulty.BASIC)
    repair["questions"][0] = _question_payload(8, Difficulty.BASIC)
    initial_question = GeneratedQuestion.model_validate(initial["questions"][0])
    repair_question = GeneratedQuestion.model_validate(repair["questions"][0])
    rejected_critique = _critique_payload(0, initial_question)
    if failure == "ambiguous_answer":
        rejected_critique["option_critiques"][1]["assessment"] = "answer"
    elif failure == "answer_leakage":
        rejected_critique["leakage_signals"] = [{"option_id": "A", "signal": "wording_echo"}]
    elif failure == "implausible_distractor":
        rejected_critique["option_critiques"][1]["same_type_and_granularity"] = False
    elif failure == "low_pedagogical_value":
        rejected_critique["pedagogical_defects"] = ["tautology"]
        rejected_critique["pedagogically_useful"] = False
    elif failure == "difficulty_mismatch":
        rejected_critique["cognitive_operation"] = "analysis"
    else:
        rejected_critique["distinct_learning_objective"] = False
    rejected_critique["reason"] = "The item failed one mandatory pedagogical dimension."
    critic = _Critic(
        critique_batches=[
            [rejected_critique],
            [_critique_payload(0, repair_question)],
        ]
    )
    model = _StructuredModel(responses=[initial, repair])
    service, _ = _service_with_model(
        model,
        critic=critic,
        documents=[_Document(page_content=PCA_EVIDENCE, metadata={})],
    )

    quiz = service.generate(GenerateQuestionsRequest(target_kc_id="pca", count=1))

    assert quiz.questions == [GeneratedQuestion.model_validate(repair["questions"][0])]
    assert model.invoke_count == 2
    assert len(critic.calls) == 2
    assert expected_rejection in model.message_batches[1][-1].content


def test_quality_verifier_failure_rejects_the_request_without_regeneration() -> None:
    class FailingVerifier:
        def verify(self, *args: Any, **kwargs: Any) -> tuple[EvidenceVerificationVerdict, ...]:
            raise AssessmentVerificationError("verifier unavailable")

    model = _StructuredModel(_quiz_payload(1, Difficulty.BASIC))
    service = AssessmentService(
        retriever=_Retriever([_Document(page_content=PCA_EVIDENCE, metadata={})]),
        generator=AssessmentGenerator(model=model),
        verifier=FailingVerifier(),
    )

    with pytest.raises(AssessmentVerificationError):
        service.generate(GenerateQuestionsRequest(target_kc_id="pca", count=1))
    assert model.invoke_count == 1


def test_service_fails_closed_when_an_injected_verifier_omits_question_coverage() -> None:
    class IncompleteVerifier:
        def verify(self, *args: Any, **kwargs: Any) -> tuple[EvidenceVerificationVerdict, ...]:
            return ()

    model = _StructuredModel(_quiz_payload(1, Difficulty.BASIC))
    service = AssessmentService(
        retriever=_Retriever([_Document(page_content=PCA_EVIDENCE, metadata={})]),
        generator=AssessmentGenerator(model=model),
        verifier=IncompleteVerifier(),
    )

    with pytest.raises(AssessmentVerificationError):
        service.generate(GenerateQuestionsRequest(target_kc_id="pca", count=1))
    assert model.invoke_count == 1


def test_service_fails_closed_when_an_injected_critic_omits_question_coverage() -> None:
    class IncompleteCritic:
        def critique(self, *args: Any, **kwargs: Any) -> tuple[ItemCritique, ...]:
            return ()

    model = _StructuredModel(_quiz_payload(1, Difficulty.BASIC))
    service = AssessmentService(
        retriever=_Retriever([_Document(page_content=PCA_EVIDENCE, metadata={})]),
        generator=AssessmentGenerator(model=model),
        verifier=_Verifier(),
        critic=IncompleteCritic(),
    )

    with pytest.raises(AssessmentCritiqueError, match="incomplete question coverage"):
        service.generate(GenerateQuestionsRequest(target_kc_id="pca", count=1))
    assert model.invoke_count == 1


def test_service_validates_excerpt_ids_from_an_injected_verifier_without_repair() -> None:
    class UnknownExcerptVerifier:
        def verify(self, *args: Any, **kwargs: Any) -> tuple[EvidenceVerificationVerdict, ...]:
            return (
                EvidenceVerificationVerdict.model_validate(
                    {
                        "question_index": 0,
                        "supported_options": [{"option_id": "A", "excerpt_id": "E999"}],
                        "on_topic": True,
                        "answer_explanation": "Unknown excerpt should fail at the service boundary.",
                    }
                ),
            )

    model = _StructuredModel(_quiz_payload(1, Difficulty.BASIC))
    service = AssessmentService(
        retriever=_Retriever([_Document(page_content=PCA_EVIDENCE, metadata={})]),
        generator=AssessmentGenerator(model=model),
        verifier=UnknownExcerptVerifier(),
    )

    with pytest.raises(AssessmentVerificationError):
        service.generate(GenerateQuestionsRequest(target_kc_id="pca", count=1))
    assert model.invoke_count == 1


def test_evidence_rejection_does_not_call_item_quality_critic() -> None:
    verifier = _Verifier(
        verdict_batches=[
            [
                {
                    "question_index": 0,
                    "supported_options": [],
                    "on_topic": True,
                    "answer_explanation": "No option is supported by the evidence.",
                }
            ]
        ]
    )
    critic = _Critic()
    model = _StructuredModel(_quiz_payload(1, Difficulty.BASIC))
    service, _ = _service_with_model(
        model,
        verifier=verifier,
        critic=critic,
        documents=[_Document(page_content=PCA_EVIDENCE, metadata={})],
    )

    with pytest.raises(AssessmentGenerationError, match="answer_not_supported"):
        service.generate(GenerateQuestionsRequest(target_kc_id="pca", count=1))

    assert model.invoke_count == 2
    assert critic.calls == []


def test_critic_failure_rejects_the_request_without_regeneration() -> None:
    class FailingCritic:
        def critique(self, *args: Any, **kwargs: Any) -> tuple[ItemCritique, ...]:
            raise AssessmentCritiqueError("critic unavailable")

    model = _StructuredModel(_quiz_payload(1, Difficulty.BASIC))
    service = AssessmentService(
        retriever=_Retriever([_Document(page_content=PCA_EVIDENCE, metadata={})]),
        generator=AssessmentGenerator(model=model),
        verifier=_Verifier(),
        critic=FailingCritic(),
    )

    with pytest.raises(AssessmentCritiqueError):
        service.generate(GenerateQuestionsRequest(target_kc_id="pca", count=1))
    assert model.invoke_count == 1


def test_critic_only_receives_evidence_accepted_candidates_and_prior_questions() -> None:
    initial = _quiz_payload(2, Difficulty.BASIC)
    repair = _quiz_payload(1, Difficulty.BASIC)
    repair["questions"][0] = _question_payload(4, Difficulty.BASIC)
    verifier = _Verifier(
        verdict_batches=[
            [
                {
                    "question_index": 0,
                    "supported_options": [{"option_id": "A", "excerpt_id": "E1"}],
                    "on_topic": True,
                    "answer_explanation": "The first candidate is supported.",
                },
                {
                    "question_index": 1,
                    "supported_options": [],
                    "on_topic": True,
                    "answer_explanation": "The second candidate is unsupported.",
                },
            ],
            [
                {
                    "question_index": 0,
                    "supported_options": [{"option_id": "A", "excerpt_id": "E1"}],
                    "on_topic": True,
                    "answer_explanation": "The repaired question is supported.",
                }
            ],
        ]
    )
    critic = _Critic()
    model = _StructuredModel(responses=[initial, repair])
    service, _ = _service_with_model(
        model,
        verifier=verifier,
        critic=critic,
        documents=[_Document(page_content=PCA_EVIDENCE, metadata={})],
    )

    quiz = service.generate(GenerateQuestionsRequest(target_kc_id="pca", count=2))

    assert quiz.questions[0] == GeneratedQuestion.model_validate(initial["questions"][0]).model_copy(
        update={"explanation": "The first candidate is supported."}
    )
    assert quiz.questions[1] == GeneratedQuestion.model_validate(repair["questions"][0]).model_copy(
        update={"explanation": "The repaired question is supported."}
    )
    assert model.invoke_count == 2
    assert critic.calls[0] == ([quiz.questions[0]], [])
    assert critic.calls[1] == ([quiz.questions[1]], [quiz.questions[0]])
    assert verifier.catalogs[0] is verifier.catalogs[1]
    assert "answer_not_supported" in model.message_batches[1][-1].content


def test_quality_verdict_requires_evidence_from_a_question_declared_source() -> None:
    first_source = "PCA 通过将原始数据投影到主要变化方向来减少特征维度并保留主要信息。"
    second_source = "PCA 的主成分通常按能够解释的方差大小进行排序。"
    verifier = _Verifier(
        verdict_batches=[
            [
                {
                    "question_index": 0,
                    "supported_options": [{"option_id": "A", "excerpt_id": "E2"}],
                    "on_topic": True,
                    "answer_explanation": "The answer is supported by S2.",
                }
            ]
        ]
    )
    model = _StructuredModel(_quiz_payload(1, Difficulty.BASIC, ["S1"]))
    service = AssessmentService(
        retriever=_Retriever(
            [
                _Document(page_content=first_source, metadata={}),
                _Document(page_content=second_source, metadata={}),
            ]
        ),
        generator=AssessmentGenerator(model=model),
        verifier=verifier,
        evidence_top_k=2,
    )

    with pytest.raises(AssessmentGenerationError, match="source_mismatch"):
        service.generate(GenerateQuestionsRequest(target_kc_id="pca", count=1))
    assert model.invoke_count == 2


@pytest.mark.parametrize("failure", ["count", "difficulty", "duplicate_stem", "invented_source", "off_topic"])
def test_service_stops_after_one_unsuccessful_repair_round(failure: str) -> None:
    payload = _quiz_payload(2, Difficulty.BASIC)
    if failure == "count":
        payload["questions"].pop()
    elif failure == "difficulty":
        payload["questions"][0]["difficulty"] = Difficulty.ADVANCED.value
    elif failure == "duplicate_stem":
        payload["questions"][1]["stem"] = payload["questions"][0]["stem"]
    elif failure == "off_topic":
        payload["questions"][0]["stem"] = "如何使用 sort_values 对结果进行排序？"
    else:
        payload["questions"][0]["source_ids"] = ["S999"]

    model = _StructuredModel(payload)
    service, _ = _service_with_model(
        model,
        documents=[_Document(page_content=PCA_EVIDENCE, metadata={})],
    )

    with pytest.raises(AssessmentGenerationError):
        service.generate(GenerateQuestionsRequest(target_kc_id="pca", count=2))

    assert model.invoke_count == 2


def test_model_failure_is_generation_error_and_never_retried() -> None:
    model = _StructuredModel(error=TimeoutError("provider timeout"))
    service, _ = _service_with_model(
        model,
        documents=[_Document(page_content=PCA_EVIDENCE, metadata={})],
    )

    with pytest.raises(AssessmentGenerationError):
        service.generate(GenerateQuestionsRequest(target_kc_id="pca", count=1))
    assert model.invoke_count == 1


def test_structured_output_validation_error_can_be_repaired_once() -> None:
    with pytest.raises(ValidationError) as validation_error:
        GenerateQuestionsRequest(target_kc_id=" ")

    model = _StructuredModel(
        responses=[
            validation_error.value,
            _quiz_payload(1, Difficulty.BASIC),
        ]
    )
    service, _ = _service_with_model(
        model,
        documents=[_Document(page_content=PCA_EVIDENCE, metadata={})],
    )

    quiz = service.generate(GenerateQuestionsRequest(target_kc_id="pca", count=1))

    assert len(quiz.questions) == 1
    assert model.invoke_count == 2


def test_retrieval_failure_is_assessment_unavailable() -> None:

    retrieval_error_service = AssessmentService(
        retriever=_Retriever(error=RuntimeError("retrieval unavailable")),
        generator=AssessmentGenerator(model=_StructuredModel(_quiz_payload(1, Difficulty.BASIC))),
    )
    with pytest.raises(AssessmentUnavailableError):
        retrieval_error_service.generate(GenerateQuestionsRequest(target_kc_id="pca", count=1))


def test_lazy_service_factory_does_not_initialize_retrieval_or_model_clients(monkeypatch) -> None:
    monkeypatch.setattr(assessment_service_module, "_assessment_service", None)

    service = get_assessment_service()

    assert isinstance(service, AssessmentService)
    assert service._retriever is None
    assert service._generator._model is None
    assert service._verifier._model is None
    assert service._critic._model is None


def test_lazy_retriever_and_model_factories_initialize_once_under_concurrency(monkeypatch) -> None:
    created_retrievers: list[object] = []
    created_generator_models: list[object] = []
    created_verifier_models: list[object] = []
    fake_retrieval_service = ModuleType("ds_course_agent.retrieval.service")
    fake_llm = ModuleType("ds_course_agent.assessment.model_factory")

    class FakeRAGService:
        def __init__(self) -> None:
            time.sleep(0.02)
            created_retrievers.append(self)

    def get_assessment_generator_model() -> object:
        time.sleep(0.02)
        model = object()
        created_generator_models.append(model)
        return model

    def get_assessment_verifier_model() -> object:
        time.sleep(0.02)
        model = object()
        created_verifier_models.append(model)
        return model

    fake_retrieval_service.RAGService = FakeRAGService
    fake_llm.get_assessment_generator_model = get_assessment_generator_model
    fake_llm.get_assessment_verifier_model = get_assessment_verifier_model
    monkeypatch.setitem(sys.modules, "ds_course_agent.retrieval.service", fake_retrieval_service)
    monkeypatch.setitem(sys.modules, "ds_course_agent.assessment.model_factory", fake_llm)

    service = AssessmentService()
    generator = AssessmentGenerator()
    verifier = AssessmentEvidenceVerifier()
    with ThreadPoolExecutor(max_workers=2) as executor:
        retrievers = list(executor.map(lambda _: service._get_retriever(), range(2)))
        generator_models = list(executor.map(lambda _: generator._resolve_model(), range(2)))
        verifier_models = list(executor.map(lambda _: verifier._resolve_model(), range(2)))

    assert len(created_retrievers) == 1
    assert retrievers[0] is retrievers[1]
    assert len(created_generator_models) == 1
    assert generator_models[0] is generator_models[1]
    assert len(created_verifier_models) == 1
    assert verifier_models[0] is verifier_models[1]
    assert generator_models[0] is not verifier_models[0]


def test_assessment_modules_respect_static_dependency_boundaries() -> None:
    forbidden_domains = (
        "ds_course_agent.agent",
        "ds_course_agent.api",
        "ds_course_agent.tools",
        "ds_course_agent.research",
        "ds_course_agent.assessment.providers",
        "ds_course_agent.shared.llm",
    )
    forbidden_eager_imports = (
        "ds_course_agent.retrieval.service",
        "langchain_core",
        "langchain_openai",
        "langchain_ollama",
        "langchain_google_genai",
        "pypdf",
    )

    for path in PACKAGE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        all_imports = []
        top_level_imports = []
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            all_imports.extend(names)
            if node in tree.body:
                top_level_imports.extend(names)

        assert not any(
            imported == forbidden or imported.startswith(f"{forbidden}.")
            for imported in all_imports
            for forbidden in forbidden_domains
        ), path
        assert not any(
            imported == forbidden or imported.startswith(f"{forbidden}.")
            for imported in top_level_imports
            for forbidden in forbidden_eager_imports
        ), path


def test_assessment_package_imports_without_optional_provider_or_client_modules() -> None:
    script = """
import builtins
import sys

blocked = {
    'ds_course_agent.retrieval.service',
    'ds_course_agent.shared.llm',
    'langchain_core',
    'langchain_openai',
    'langchain_ollama',
    'langchain_google_genai',
    'pypdf',
}
original_import = builtins.__import__

def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if any(name == module or name.startswith(module + '.') for module in blocked):
        raise ModuleNotFoundError(name)
    return original_import(name, globals, locals, fromlist, level)

builtins.__import__ = guarded_import
import ds_course_agent.assessment

loaded = set(sys.modules)
assert not any(name == module or name.startswith(module + '.') for module in blocked for name in loaded)
"""

    result = run_python_script(script)

    assert result.returncode == 0, result.stdout + result.stderr
