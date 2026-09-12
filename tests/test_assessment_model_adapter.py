"""Exercise the real structured-output adapter without provider network calls."""

from __future__ import annotations

import json
from collections.abc import Sequence
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.documents import Document
from langchain_openai import ChatOpenAI

from ds_course_agent.assessment.critic import ItemCritique
from ds_course_agent.assessment.generator import AssessmentGenerationError, AssessmentGenerator
from ds_course_agent.assessment.models import EvidenceSource, GeneratedQuestion, GenerateQuestionsRequest
from ds_course_agent.assessment.service import AssessmentService
from ds_course_agent.assessment.verifier import EvidenceExcerptCatalog, EvidenceVerificationVerdict


class TextbookRetriever:
    """Return a single fixed textbook passage without loading a knowledge base."""

    def retrieve(self, question: str, top_k: int | None = None) -> SimpleNamespace:
        return SimpleNamespace(
            documents=[Document(page_content="PCA reduces feature dimensionality.", metadata={"source": "book.pdf"})]
        )


class PassVerifier:
    """Accept adapter-test questions without issuing a second provider request."""

    def verify(
        self,
        request: GenerateQuestionsRequest,
        questions: Sequence[GeneratedQuestion],
        catalog: EvidenceExcerptCatalog,
    ) -> tuple[EvidenceVerificationVerdict, ...]:
        del request, catalog
        return tuple(
            EvidenceVerificationVerdict(
                question_index=index,
                supported_options=[
                    {
                        "option_id": question.correct_option_id,
                        "excerpt_id": "E1",
                    }
                ],
                on_topic=True,
                answer_explanation="Accepted by the adapter test verifier.",
            )
            for index, question in enumerate(questions)
        )


class PassCritic:
    """Accept adapter-test questions without issuing another provider request."""

    def critique(
        self,
        request: GenerateQuestionsRequest,
        questions: Sequence[GeneratedQuestion],
        accepted_questions: Sequence[GeneratedQuestion] = (),
    ) -> tuple[ItemCritique, ...]:
        del request, accepted_questions
        return tuple(
            ItemCritique.model_validate(
                {
                    "question_index": index,
                    "option_critiques": [
                        {
                            "option_id": option.id,
                            "assessment": "answer" if option.id == question.correct_option_id else "distractor",
                            "same_type_and_granularity": True,
                            "reason": "The option is structurally plausible.",
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
                    "learning_objective": "PCA dimensionality reduction",
                    "reason": "Accepted by the adapter test critic.",
                }
            )
            for index, question in enumerate(questions)
        )


@pytest.mark.parametrize("failure", ["none", "invalid_answer", "wrong_function"])
def test_real_structured_adapter_validates_provider_json(failure: str) -> None:
    payload = {
        "title": "PCA practice",
        "questions": [
            {
                "stem": "What is PCA used for?",
                "options": [
                    {"id": "A", "text": "Dimensionality reduction"},
                    {"id": "B", "text": "Adding observations"},
                    {"id": "C", "text": "Deleting every feature"},
                    {"id": "D", "text": "Guaranteeing zero error"},
                ],
                "correct_option_id": "Z" if failure == "invalid_answer" else "A",
                "explanation": "PCA reduces feature dimensionality.",
                "difficulty": "basic",
                "source_ids": ["S1"],
            }
        ],
    }
    requests: list[dict] = []

    def respond(request: httpx.Request) -> httpx.Response:
        request_payload = json.loads(request.content)
        requests.append(request_payload)
        tool_name = request_payload["tools"][0]["function"]["name"]
        return httpx.Response(
            200,
            json={
                "id": "local-test",
                "object": "chat.completion",
                "created": 0,
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-local-test",
                                    "type": "function",
                                    "function": {
                                        "name": "WrongQuiz"
                                        if failure == "wrong_function" and len(requests) == 1
                                        else tool_name,
                                        "arguments": json.dumps(payload),
                                    },
                                }
                            ],
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
        service = AssessmentService(
            retriever=TextbookRetriever(),
            generator=AssessmentGenerator(model=model),
            verifier=PassVerifier(),
            critic=PassCritic(),
        )
        request = GenerateQuestionsRequest(target_kc_id="pca", count=1)
        if failure == "invalid_answer":
            with pytest.raises(AssessmentGenerationError):
                service.generate(request)
        else:
            quiz = service.generate(request)
            assert quiz.questions[0].correct_option_id == "A"
            assert quiz.questions[0].source_ids == [quiz.sources[0].id]
            assert quiz.sources[0].text == "PCA reduces feature dimensionality."

    assert len(requests) == (1 if failure == "none" else 2)
    assert requests[0]["tools"][0]["type"] == "function"
    assert requests[0]["tools"][0]["function"]["parameters"]["type"] == "object"
    assert requests[0]["tool_choice"]["type"] == "function"
    assert "response_format" not in requests[0]
