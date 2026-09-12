"""Focused contracts for answer-blind assessment item criticism."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from ds_course_agent.assessment.critic import (
    AssessmentCritiqueError,
    AssessmentQualityCritic,
    CritiqueBatch,
    ItemCritique,
)
from ds_course_agent.assessment.models import (
    MAX_QUESTIONS,
    Difficulty,
    GeneratedQuestion,
    GenerateQuestionsRequest,
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
        self.schema: Any = None
        self.structured_kwargs: dict[str, Any] = {}
        self.messages: list[Any] | None = None
        self.invoke_count = 0

    def with_structured_output(self, schema: Any, **kwargs: Any) -> _Runnable:
        self.schema = schema
        self.structured_kwargs = kwargs
        return _Runnable(self)


def _request() -> GenerateQuestionsRequest:
    return GenerateQuestionsRequest(target_kc_id="pca", count=1, difficulty=Difficulty.INTERMEDIATE)


def _question(
    index: int = 0,
    *,
    stem: str | None = None,
    option_texts: list[str] | None = None,
    correct_option_id: str = "A",
    explanation: str = "PCA projects data onto directions of high variance.",
    source_ids: list[str] | None = None,
) -> GeneratedQuestion:
    option_ids = ("A", "B", "C", "D")
    resolved_option_texts = option_texts or [f"Option {item} for question {index + 1}" for item in option_ids]
    return GeneratedQuestion.model_validate(
        {
            "stem": stem or f"Question {index + 1}: What is PCA primarily used for?",
            "options": [
                {
                    "id": option_id,
                    "text": resolved_option_texts[offset],
                }
                for offset, option_id in enumerate(option_ids)
            ],
            "correct_option_id": correct_option_id,
            "explanation": explanation,
            "difficulty": Difficulty.INTERMEDIATE.value,
            "source_ids": source_ids or ["S1"],
        }
    )


def _large_question(index: int) -> GeneratedQuestion:
    stem_prefix = f"Question {index}: "
    stem = stem_prefix + "x" * (600 - len(stem_prefix))
    option_texts = []
    for option_id in ("A", "B", "C", "D"):
        prefix = f"Option {option_id} for question {index}: "
        option_texts.append(prefix + "x" * (400 - len(prefix)))
    return _question(index, stem=stem, option_texts=option_texts)


def _critique_payload(index: int = 0) -> dict[str, Any]:
    return {
        "question_index": index,
        "option_critiques": [
            {
                "option_id": option_id,
                "assessment": "answer" if option_id == "A" else "distractor",
                "same_type_and_granularity": True,
                "reason": f"Option {option_id} is plausible and parallel.",
            }
            for option_id in ("A", "B", "C", "D")
        ],
        "leakage_signals": [],
        "pedagogical_defects": [],
        "pedagogically_useful": True,
        "cognitive_operation": "application",
        "distinct_learning_objective": True,
        "learning_objective": "Explain PCA dimensionality reduction.",
        "reason": "The item has a single apparent answer and plausible distractors.",
    }


def _human_prompt(model: _Model) -> str:
    assert model.messages is not None
    return str(model.messages[-1].content)


def test_critic_uses_json_schema_structured_output() -> None:
    model = _Model({"critiques": [_critique_payload()]})

    critiques = AssessmentQualityCritic(model=model).critique(_request(), [_question()])

    assert [critique.question_index for critique in critiques] == [0]
    assert model.schema["properties"]["critiques"]["minItems"] == 1
    assert model.schema["properties"]["critiques"]["maxItems"] == 1
    assert model.schema["$defs"]["ItemCritique"]["properties"]["question_index"]["exclusiveMaximum"] == 1
    assert model.structured_kwargs == {"method": "json_schema"}
    assert model.invoke_count == 1


def test_critic_schema_declares_unique_quality_signal_arrays() -> None:
    item_schema = CritiqueBatch.model_json_schema()["$defs"]["ItemCritique"]["properties"]

    assert "apparent_correct_option_ids" not in item_schema
    assert item_schema["leakage_signals"]["uniqueItems"] is True
    assert item_schema["pedagogical_defects"]["uniqueItems"] is True


@pytest.mark.parametrize("assessment", [None, "", "factually_incorrect", ["answer", "irrelevant"]])
def test_option_requires_one_valid_exclusive_role(assessment: Any) -> None:
    payload = _critique_payload()
    payload["option_critiques"][1]["assessment"] = assessment
    with pytest.raises(ValidationError):
        ItemCritique.model_validate(payload)


def test_apparent_answers_are_derived_from_roles_including_ambiguous_items() -> None:
    payload = _critique_payload()
    payload["option_critiques"][1]["assessment"] = "answer"
    assert ItemCritique.model_validate(payload).apparent_correct_option_ids == ["A", "B"]
    payload["apparent_correct_option_ids"] = ["A"]
    with pytest.raises(ValidationError):
        ItemCritique.model_validate(payload)


def test_critic_rejects_removed_boolean_plausibility_contract() -> None:
    payload = _critique_payload()
    payload["option_critiques"][1]["plausible_for_unmastered_student"] = False
    with pytest.raises(ValidationError):
        ItemCritique.model_validate(payload)


def test_apparent_answer_cannot_simultaneously_be_an_invalid_distractor() -> None:
    payload = _critique_payload()
    payload["option_critiques"][0]["defect"] = "irrelevant"
    with pytest.raises(ValidationError):
        ItemCritique.model_validate(payload)


def test_critic_observes_operation_without_seeing_requested_or_candidate_difficulty() -> None:
    model = _Model({"critiques": [_critique_payload()]})
    critic = AssessmentQualityCritic(model=model)
    candidate = _question()
    prompts = []
    for difficulty in Difficulty:
        request = GenerateQuestionsRequest(target_kc_id="pca", count=1, difficulty=difficulty)
        critic.critique(request, [candidate.model_copy(update={"difficulty": difficulty})])
        prompts.append(_human_prompt(model))

    assert len(set(prompts)) == 1
    assert "请求难度" not in prompts[0]


def test_critic_rejects_removed_difficulty_approval_boolean() -> None:
    payload = _critique_payload()
    payload["difficulty_appropriate"] = True
    with pytest.raises(ValidationError):
        ItemCritique.model_validate(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"critiques": [_critique_payload(1)]},
        {"critiques": [_critique_payload(0), _critique_payload(0)]},
    ],
)
def test_critic_fails_closed_on_incomplete_or_duplicate_question_coverage(payload: dict[str, Any]) -> None:
    model = _Model(payload)
    critic = AssessmentQualityCritic(model=model)

    with pytest.raises(AssessmentCritiqueError, match="incomplete question coverage"):
        critic.critique(_request(), [_question(0), _question(1)])

    assert model.invoke_count == 1


@pytest.mark.parametrize("option_ids", [("A", "B", "C", "C"), ("A", "B", "C")])
def test_item_critique_requires_exact_a_b_c_d_coverage(option_ids: tuple[str, ...]) -> None:
    payload = _critique_payload()
    payload["option_critiques"] = payload["option_critiques"][: len(option_ids)]
    for critique, option_id in zip(payload["option_critiques"], option_ids, strict=True):
        critique["option_id"] = option_id

    with pytest.raises(ValidationError):
        ItemCritique.model_validate(payload)


@pytest.mark.parametrize(
    "location",
    ["option_critiques", "leakage_signals"],
)
def test_item_critique_rejects_unknown_option_ids(location: str) -> None:
    payload = _critique_payload()
    if location == "option_critiques":
        payload[location][0]["option_id"] = "Z"
    else:
        payload[location] = [{"option_id": "Z", "signal": "length_outlier"}]

    with pytest.raises(ValidationError):
        ItemCritique.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("leakage_signals", [{"option_id": "A", "signal": "not_a_signal"}]),
        ("pedagogical_defects", ["not_a_defect"]),
    ],
)
def test_item_critique_rejects_invalid_enums(field: str, value: list[Any]) -> None:
    payload = _critique_payload()
    payload[field] = value

    with pytest.raises(ValidationError):
        ItemCritique.model_validate(payload)


def test_item_critique_rejects_duplicate_leakage_signals() -> None:
    payload = _critique_payload()
    payload["leakage_signals"] = [
        {"option_id": "A", "signal": "length_outlier"},
        {"option_id": "A", "signal": "length_outlier"},
    ]

    with pytest.raises(ValidationError):
        ItemCritique.model_validate(payload)


def test_item_critique_rejects_duplicate_pedagogical_defects() -> None:
    payload = _critique_payload()
    payload["pedagogical_defects"] = ["weak_distractors", "weak_distractors"]
    payload["pedagogically_useful"] = False

    with pytest.raises(ValidationError):
        ItemCritique.model_validate(payload)


def test_item_critique_keeps_usefulness_and_defects_as_independent_signals() -> None:
    payload = _critique_payload()
    payload["pedagogical_defects"] = ["weak_distractors"]

    critique = ItemCritique.model_validate(payload)

    assert critique.pedagogically_useful is True
    assert [defect.value for defect in critique.pedagogical_defects] == ["weak_distractors"]


def test_critic_prompt_hides_answers_explanations_source_ids_and_textbook_evidence() -> None:
    model = _Model({"critiques": [_critique_payload()]})
    candidate = _question(
        stem="CANDIDATE_STEM",
        correct_option_id="D",
        explanation="CANDIDATE_EXPLANATION_SECRET",
        source_ids=["TEXTBOOK_EVIDENCE_SENTINEL"],
    )

    AssessmentQualityCritic(model=model).critique(_request(), [candidate])

    prompt = _human_prompt(model)
    assert "CANDIDATE_STEM" in prompt
    assert "CANDIDATE_EXPLANATION_SECRET" not in prompt
    assert "TEXTBOOK_EVIDENCE_SENTINEL" not in prompt
    assert "correct_option_id" not in prompt
    assert "explanation" not in prompt
    assert "source_ids" not in prompt
    assert "教材证据" not in prompt


def test_critic_projects_accepted_questions_to_stems_and_options_only() -> None:
    model = _Model({"critiques": [_critique_payload()]})
    accepted = _question(
        stem="ACCEPTED_STEM",
        option_texts=["ACCEPTED_OPTION_A", "ACCEPTED_OPTION_B", "ACCEPTED_OPTION_C", "ACCEPTED_OPTION_D"],
        correct_option_id="C",
        explanation="ACCEPTED_EXPLANATION_SECRET",
        source_ids=["ACCEPTED_SOURCE_ID_SECRET"],
    )

    AssessmentQualityCritic(model=model).critique(_request(), [_question()], [accepted])

    prompt = _human_prompt(model)
    assert "ACCEPTED_STEM" in prompt
    for option_id in ("A", "B", "C", "D"):
        assert f"ACCEPTED_OPTION_{option_id}" in prompt
    assert "ACCEPTED_EXPLANATION_SECRET" not in prompt
    assert "ACCEPTED_SOURCE_ID_SECRET" not in prompt
    assert "correct_option_id" not in prompt
    assert "explanation" not in prompt
    assert "source_ids" not in prompt


def test_critic_rejects_an_oversized_prompt_before_model_call() -> None:
    model = _Model()
    questions = [_large_question(index) for index in range(MAX_QUESTIONS)]
    accepted_questions = [_large_question(index + MAX_QUESTIONS) for index in range(MAX_QUESTIONS)]

    with pytest.raises(AssessmentCritiqueError, match="bounded context"):
        AssessmentQualityCritic(model=model).critique(_request(), questions, accepted_questions)

    assert model.schema is None
    assert model.invoke_count == 0


def test_critic_provider_failure_fails_closed_without_retry() -> None:
    model = _Model(error=TimeoutError("provider timeout"))

    with pytest.raises(AssessmentCritiqueError, match="pedagogical critique failed"):
        AssessmentQualityCritic(model=model).critique(_request(), [_question()])

    assert model.invoke_count == 1


def test_real_critic_adapter_sends_bounded_schema_without_reviewing_history() -> None:
    import json

    import httpx
    from langchain_openai import ChatOpenAI

    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "critic-local-test",
                "object": "chat.completion",
                "created": 0,
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps({"critiques": [_critique_payload()]}),
                        },
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 30, "total_tokens": 40},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        model = ChatOpenAI(
            model="test-model",
            api_key="test-placeholder",
            base_url="https://provider.invalid/v1",
            http_client=client,
            max_retries=0,
        )
        verdicts = AssessmentQualityCritic(model=model).critique(_request(), [_question()], [_question(1)])

    assert len(requests) == 1
    schema = requests[0]["response_format"]["json_schema"]["schema"]
    assert schema["properties"]["critiques"]["minItems"] == 1
    assert schema["properties"]["critiques"]["maxItems"] == 1
    assert [v.question_index for v in verdicts] == [0]
    assert verdicts[0].apparent_correct_option_ids == ["A"]
