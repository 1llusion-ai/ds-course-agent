"""Tests for the production two-call assessment path."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from ds_course_agent.assessment.generator import AssessmentOutputError
from ds_course_agent.assessment.models import Difficulty, GeneratedQuestion, GenerateQuestionsRequest, QuizDraft
from ds_course_agent.assessment.service import AssessmentService, AssessmentStructuralFailureError

PCA_EVIDENCE = "PCA 通过将原始数据投影到主要变化方向来减少特征维度。"


@dataclass
class _Document:
    page_content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class _RetrievalResult:
    documents: list[_Document]


class _Retriever:
    def retrieve(self, question: str, top_k: int | None = None) -> _RetrievalResult:
        del question, top_k
        return _RetrievalResult([_Document(PCA_EVIDENCE, {})])


class _GateMustNotRun:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"simplified generation must not call quality gate: {name}")


class _Generator:
    def __init__(self, *, invalid_source: bool = False) -> None:
        self.candidate_counts: list[int | None] = []
        self.invalid_source = invalid_source

    def generate_candidates(self, context, sources, *, exposure, candidate_count=None) -> QuizDraft:
        del exposure
        self.candidate_counts.append(candidate_count)
        questions = []
        for index in range(context.request.count):
            questions.append(
                GeneratedQuestion(
                    stem=f"第 {index + 1} 题：PCA 主要用于什么？",
                    options=(
                        {"id": "A", "text": f"降低特征维度（{index}）"},
                        {"id": "B", "text": f"增加样本数量（{index}）"},
                        {"id": "C", "text": f"替代数据清洗（{index}）"},
                        {"id": "D", "text": f"保证模型零误差（{index}）"},
                    ),
                    correct_option_id="A",
                    explanation="教材说明 PCA 可以减少特征维度。",
                    difficulty=Difficulty.BASIC,
                    source_ids=["S2" if self.invalid_source else "S1"],
                )
            )
        return QuizDraft(title="PCA 练习", questions=questions)


class _OutputFailureGenerator:
    def generate_candidates(self, *args, **kwargs):
        del args, kwargs
        raise AssessmentOutputError("malformed structured output")


@pytest.mark.parametrize(
    ("count", "expected_candidates"),
    [(2, 4), (5, 8)],
)
def test_simplified_service_uses_candidate_pool_without_quality_gates(count: int, expected_candidates: int) -> None:
    generator = _Generator()
    service = AssessmentService(
        retriever=_Retriever(),
        generator=generator,
        verifier=_GateMustNotRun(),
        critic=_GateMustNotRun(),
        strict_quality=False,
    )

    quiz = service.generate(GenerateQuestionsRequest(target_kc_id="pca", count=count))

    assert len(quiz.questions) == count
    assert quiz.review_certificates == ()
    assert generator.candidate_counts == [expected_candidates]


def test_simplified_service_blocks_deterministic_source_failures_without_retry() -> None:
    generator = _Generator(invalid_source=True)
    service = AssessmentService(
        retriever=_Retriever(),
        generator=generator,
        verifier=_GateMustNotRun(),
        critic=_GateMustNotRun(),
        strict_quality=False,
    )

    with pytest.raises(AssessmentStructuralFailureError) as error:
        service.generate(GenerateQuestionsRequest(target_kc_id="pca", count=2))

    assert error.value.retryable is False
    assert generator.candidate_counts == [4]


def test_simplified_service_allows_boundary_retry_for_structured_output_only() -> None:
    service = AssessmentService(
        retriever=_Retriever(),
        generator=_OutputFailureGenerator(),
        verifier=_GateMustNotRun(),
        critic=_GateMustNotRun(),
        strict_quality=False,
    )

    with pytest.raises(AssessmentOutputError):
        service.generate(GenerateQuestionsRequest(target_kc_id="pca", count=2))
