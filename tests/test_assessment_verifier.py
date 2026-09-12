"""Contracts for the independent evidence-grounded assessment verifier."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from ds_course_agent.assessment.feedback import QuestionRejectionCode
from ds_course_agent.assessment.models import (
    Difficulty,
    EvidenceSource,
    GeneratedQuestion,
    GenerateQuestionsRequest,
)
from ds_course_agent.assessment.service import AssessmentService
from ds_course_agent.assessment.verifier import (
    AssessmentEvidenceVerifier,
    AssessmentVerificationError,
    EvidenceExcerpt,
    EvidenceExcerptCatalog,
    EvidenceVerificationBatch,
    EvidenceVerificationVerdict,
)


class _Runnable:
    def __init__(self, owner: _Model) -> None:
        self._owner = owner

    def invoke(self, messages: list[Any]) -> Any:
        self._owner.messages = messages
        self._owner.invoke_count += 1
        if self._owner.error is not None:
            raise self._owner.error
        return self._owner.response


class _Model:
    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.schema: type[Any] | None = None
        self.structured_kwargs: dict[str, Any] = {}
        self.messages: list[Any] | None = None
        self.invoke_count = 0

    def with_structured_output(self, schema: type[Any], **kwargs: Any) -> _Runnable:
        self.schema = schema
        self.structured_kwargs = kwargs
        return _Runnable(self)


def _question(index: int = 0) -> GeneratedQuestion:
    return GeneratedQuestion.model_validate(
        {
            "stem": f"PCA 题目 {index + 1}：PCA 的主要用途是什么？",
            "options": [
                {"id": "A", "text": "降低特征维度"},
                {"id": "B", "text": "增加样本数量"},
                {"id": "C", "text": "替代数据清洗"},
                {"id": "D", "text": "保证零误差"},
            ],
            "correct_option_id": "A",
            "explanation": "教材说明 PCA 用于降低特征维度。",
            "difficulty": "basic",
            "source_ids": ["S1"],
        }
    )


def _verdict(index: int, **updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "question_index": index,
        "supported_options": [
            {
                "option_id": "A",
                "excerpt_id": "E1",
            }
        ],
        "on_topic": True,
        "answer_explanation": "The answer is uniquely supported by S1.",
    }
    payload.update(updates)
    return payload


def _catalog(*sources: EvidenceSource) -> EvidenceExcerptCatalog:
    return EvidenceExcerptCatalog.from_sources(sources)


def test_verifier_uses_structured_output_and_server_owned_excerpts() -> None:
    model = _Model({"verdicts": [_verdict(0)]})
    verifier = AssessmentEvidenceVerifier(model=model)
    source = EvidenceSource(id="S1", text="PCA 通过投影保留主要变化方向来降低特征维度。")

    verdicts = verifier.verify(
        GenerateQuestionsRequest(target_kc_id="pca", count=1),
        [_question()],
        _catalog(source),
    )

    assert [support.option_id for support in verdicts[0].supported_options] == ["A"]
    assert model.schema is EvidenceVerificationBatch
    assert model.structured_kwargs == {"method": "json_schema"}
    assert model.invoke_count == 1
    assert model.messages is not None
    prompt = model.messages[-1].content
    assert source.text in prompt
    assert "[source_id=S1]" in prompt
    assert "[E1]" in prompt
    assert "correct_option_id" not in prompt
    assert "source_ids" not in prompt
    assert "question_index=0" in prompt


@pytest.mark.parametrize(
    "payload",
    [
        {"verdicts": [_verdict(1)]},
        {"verdicts": [_verdict(0), _verdict(0)]},
    ],
)
def test_verifier_fails_closed_on_incomplete_or_duplicate_coverage(payload: dict[str, object]) -> None:
    verifier = AssessmentEvidenceVerifier(model=_Model(payload))
    source = EvidenceSource(id="S1", text="PCA 通过投影保留主要变化方向来降低特征维度。")

    with pytest.raises(AssessmentVerificationError):
        verifier.verify(GenerateQuestionsRequest(target_kc_id="pca"), [_question()], _catalog(source))


@pytest.mark.parametrize("field", ["on_topic"])
def test_verdict_contract_requires_strict_boolean_dimensions(field: str) -> None:
    with pytest.raises(ValidationError):
        EvidenceVerificationVerdict.model_validate(_verdict(0, **{field: "true"}))


def test_catalog_rejects_unknown_excerpt_ids() -> None:
    payload = _verdict(0)
    payload["supported_options"][0]["excerpt_id"] = "E999"
    source = EvidenceSource(id="S1", text="PCA 通过投影保留主要变化方向来降低特征维度。")

    with pytest.raises(AssessmentVerificationError):
        _catalog(source).validate_verdicts([EvidenceVerificationVerdict.model_validate(payload)], [_question()])


def test_source_ownership_is_derived_and_model_cannot_override_it() -> None:
    sources = [
        EvidenceSource(id="S1", text="PCA 通过投影保留主要变化方向来降低特征维度。"),
        EvidenceSource(id="S2", text="第二条独立教材证据。"),
    ]
    catalog = _catalog(*sources)
    assert catalog.source_id_for("E1") == "S1"
    assert catalog.source_id_for("E2") == "S2"
    with pytest.raises(AssessmentVerificationError):
        catalog.source_id_for("E999")
    payload = _verdict(0)
    payload["supported_options"][0]["source_id"] = "S2"
    with pytest.raises(ValidationError):
        EvidenceVerificationVerdict.model_validate(payload)


def test_catalog_removes_machine_references_from_student_explanations() -> None:
    catalog = _catalog(
        EvidenceSource(id="S1", text="第一条证据。\n第二条证据。"),
        EvidenceSource(id="S2", text="第三条证据。"),
    )

    explanation = "根据教材证据[E1]和[E2]，结论成立；因为[E3]明确指出该性质。相关示例（[S2]）也已给出。"

    assert (
        catalog.student_explanation(explanation) == "根据教材内容，结论成立；因为教材明确指出该性质。相关示例也已给出。"
    )
    with pytest.raises(AssessmentVerificationError, match="unknown evidence"):
        catalog.student_explanation("证据 E999 支持这个判断。")


def test_verifier_rejects_removed_free_text_quote_contract() -> None:
    payload = _verdict(0)
    payload["supported_options"][0].pop("excerpt_id")
    payload["supported_options"][0]["quote"] = "PCA 通过投影保留主要变化方向来降低特征维度。"
    source = EvidenceSource(id="S1", text="PCA 通过投影保留主要变化方向来降低特征维度。")

    with pytest.raises(AssessmentVerificationError):
        AssessmentEvidenceVerifier(model=_Model({"verdicts": [payload]})).verify(
            GenerateQuestionsRequest(target_kc_id="pca"), [_question()], _catalog(source)
        )


def test_catalog_uses_stable_nonempty_source_lines_without_resplitting() -> None:
    sources = [
        EvidenceSource(id="S1", text="第一条完整证据。\n\n 第二条完整证据；仍属于同一行。 "),
        EvidenceSource(id="S2", text="第三条完整证据。"),
    ]

    first = _catalog(*sources)
    second = _catalog(*sources)

    assert first == second
    assert first.excerpts == (
        EvidenceExcerpt(id="E1", source_id="S1", text="第一条完整证据。"),
        EvidenceExcerpt(id="E2", source_id="S1", text="第二条完整证据；仍属于同一行。"),
        EvidenceExcerpt(id="E3", source_id="S2", text="第三条完整证据。"),
    )


def test_catalog_rejects_duplicate_excerpt_ids_and_oversized_lines() -> None:
    source = EvidenceSource(id="S1", text="有效证据")
    duplicate_excerpts = (
        EvidenceExcerpt(id="E1", source_id="S1", text="第一条"),
        EvidenceExcerpt(id="E1", source_id="S1", text="第二条"),
    )

    with pytest.raises(AssessmentVerificationError):
        EvidenceExcerptCatalog(sources=(source,), excerpts=duplicate_excerpts)
    with pytest.raises(AssessmentVerificationError):
        EvidenceExcerptCatalog.from_sources([EvidenceSource(id="S1", text="甲" * 1_201)])


def test_catalog_rejects_duplicate_option_evidence() -> None:
    payload = _verdict(0)
    payload["supported_options"].append(dict(payload["supported_options"][0]))
    source = EvidenceSource(id="S1", text="PCA 通过投影保留主要变化方向来降低特征维度。")

    with pytest.raises(AssessmentVerificationError):
        _catalog(source).validate_verdicts([EvidenceVerificationVerdict.model_validate(payload)], [_question()])


def test_verifier_rejects_duplicate_source_ids_before_a_model_call() -> None:
    model = _Model({"verdicts": [_verdict(0)]})
    sources = [
        EvidenceSource(id="S1", text="PCA 通过投影保留主要变化方向来降低特征维度。"),
        EvidenceSource(id="S1", text="另一条 PCA 证据。"),
    ]

    with pytest.raises(AssessmentVerificationError):
        EvidenceExcerptCatalog.from_sources(sources)
    assert model.invoke_count == 0


def test_verifier_prompt_hides_candidate_and_accepted_answers_and_explanations() -> None:
    model = _Model({"verdicts": [_verdict(0)]})
    verifier = AssessmentEvidenceVerifier(model=model)
    candidate = _question().model_copy(update={"explanation": "CANDIDATE_SECRET_EXPLANATION"})
    sources = [
        EvidenceSource(id="S1", text="PCA 通过投影保留主要变化方向来降低特征维度。"),
        EvidenceSource(id="S2", text="UNDECLARED_SOURCE_SENTINEL"),
    ]

    verifier.verify(GenerateQuestionsRequest(target_kc_id="pca"), [candidate], _catalog(*sources))

    assert model.messages is not None
    prompt = model.messages[-1].content
    assert "CANDIDATE_SECRET_EXPLANATION" not in prompt
    assert "correct_option_id" not in prompt
    assert "source_ids" not in prompt
    assert "UNDECLARED_SOURCE_SENTINEL" in prompt


def test_verifier_rejects_an_oversized_prompt_before_model_call() -> None:
    model = _Model({"verdicts": [_verdict(0)]})
    verifier = AssessmentEvidenceVerifier(model=model)
    large_text = "\n".join("甲" * 1_200 for _ in range(26))
    catalog = _catalog(
        EvidenceSource(id="S1", text=large_text),
        EvidenceSource(id="S2", text=large_text),
    )

    with pytest.raises(AssessmentVerificationError):
        verifier.verify(GenerateQuestionsRequest(target_kc_id="pca"), [_question()], catalog)
    assert model.invoke_count == 0


def test_verifier_provider_failure_is_not_retried() -> None:
    model = _Model(error=TimeoutError("provider timeout"))
    verifier = AssessmentEvidenceVerifier(model=model)
    source = EvidenceSource(id="S1", text="PCA 通过投影保留主要变化方向来降低特征维度。")

    with pytest.raises(AssessmentVerificationError):
        verifier.verify(GenerateQuestionsRequest(target_kc_id="pca"), [_question()], _catalog(source))
    assert model.invoke_count == 1
    assert _question().difficulty is Difficulty.BASIC


def test_formula_answer_requires_exact_valid_evidence_tokens() -> None:
    question = GeneratedQuestion.model_validate(
        {
            "stem": "增益率的定义公式是哪一项？",
            "options": [
                {"id": "A", "text": r"$G_r(D,a)=\frac{G(D,a)}{H_a(D)}$"},
                {"id": "B", "text": r"$G_r(D,a)=\frac{G(D | a)}{H_a(D)}$"},
                {"id": "C", "text": r"$G_r(D,a)=G(D | a)H_a(D)$"},
                {"id": "D", "text": r"$G_r(D,a)=H_a(D)$"},
            ],
            "correct_option_id": "A",
            "explanation": "候选解析",
            "difficulty": "basic",
            "source_ids": ["S1"],
        }
    )
    catalog = _catalog(EvidenceSource(id="S1", text=r"增益率定义为 $G_r(D,a)=\frac{G(D | a)}{H_a(D)}$。"))
    verdict = EvidenceVerificationVerdict.model_validate(_verdict(0))

    assert (
        AssessmentService._verification_rejection_code(question, verdict, catalog)
        is QuestionRejectionCode.FORMULA_MISMATCH
    )


def test_plain_textbook_formula_exactly_matching_option_is_accepted() -> None:
    question = GeneratedQuestion.model_validate(
        {
            "stem": "增益率的定义公式是哪一项？",
            "options": [
                {"id": "A", "text": r"$G_r(D,a)=\frac{G(D | a)}{H_a(D)}$"},
                {"id": "B", "text": r"$G_r(D,a)=\frac{G(D,a)}{H_a(D)}$"},
                {"id": "C", "text": r"$G_r(D,a)=G(D | a)H_a(D)$"},
                {"id": "D", "text": r"$G_r(D,a)=H_a(D)$"},
            ],
            "correct_option_id": "A",
            "explanation": "候选解析",
            "difficulty": "basic",
            "source_ids": ["S1"],
        }
    )
    catalog = _catalog(
        EvidenceSource(
            id="S1",
            text=r"可以使用特征熵的倒数进行抑制，即增益率 G_r(D,a) = \frac{G(D | a)}{H_a(D)} 这正是 C4.5 的核心。",
        )
    )
    verdict = EvidenceVerificationVerdict.model_validate(_verdict(0))

    assert AssessmentService._verification_rejection_code(question, verdict, catalog) is None


@pytest.mark.parametrize("explanation", ["教材可能笔误，因此选择最接近的一项。", "结合上下文推断 A 正确。"])
def test_uncertain_or_corrective_verifier_explanations_are_rejected(explanation: str) -> None:
    catalog = _catalog(EvidenceSource(id="S1", text="PCA 通过投影保留主要变化方向来降低特征维度。"))
    verdict = EvidenceVerificationVerdict.model_validate(_verdict(0, answer_explanation=explanation))

    assert (
        AssessmentService._verification_rejection_code(_question(), verdict, catalog)
        is QuestionRejectionCode.UNCERTAIN_EVIDENCE
    )
