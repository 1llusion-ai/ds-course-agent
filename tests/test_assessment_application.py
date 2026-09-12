"""Assessment assignment and lifecycle invariants."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ds_course_agent.assessment.application import (
    AssessmentApplicationService,
    AssessmentNotFoundError,
    AssessmentStateError,
    AssessmentSubmissionError,
)
from ds_course_agent.assessment.models import GeneratedQuiz, GenerateQuestionsRequest
from ds_course_agent.assessment.records import AnswerSubmission, AssessmentStatus
from ds_course_agent.assessment.repository import AssessmentRepository


class StubGenerator:
    """Return one fixed grounded quiz and record the agent-selected request."""

    def __init__(self) -> None:
        self.requests: list[GenerateQuestionsRequest] = []

    def generate(self, request: GenerateQuestionsRequest) -> GeneratedQuiz:
        self.requests.append(request)
        return GeneratedQuiz.model_validate(
            {
                "title": "支持向量机测验",
                "questions": [
                    {
                        "stem": "支持向量机寻找分类超平面时会最大化什么？",
                        "options": [
                            {"id": "A", "text": "特征数量"},
                            {"id": "B", "text": "类别间隔"},
                            {"id": "C", "text": "聚类数量"},
                            {"id": "D", "text": "样本数量"},
                        ],
                        "correct_option_id": "B",
                        "explanation": "最优超平面最大化类别之间的几何间隔。",
                        "difficulty": request.difficulty,
                        "source_ids": ["source-1"],
                    }
                ],
                "sources": [
                    {
                        "id": "source-1",
                        "text": "最优分类超平面使两个类别之间的几何间隔最大。",
                        "source": "数据科学导论",
                        "page": 121,
                    }
                ],
            }
        )


class MutableClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 12, 8, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def lifecycle(tmp_path):
    generator = StubGenerator()
    clock = MutableClock()
    ids = iter(("assessment-1", "question-1"))
    service = AssessmentApplicationService(
        repository=AssessmentRepository(tmp_path / "assessment.db"),
        generator=generator,
        clock=clock,
        id_factory=lambda: next(ids),
    )
    request = GenerateQuestionsRequest(target_kc_id="svm", difficulty="intermediate", count=1)
    summary = service.assign("student-1", request)
    return service, generator, clock, summary


def test_assignment_parameters_are_internal_and_persisted(lifecycle) -> None:
    service, generator, _clock, summary = lifecycle

    assert generator.requests == [GenerateQuestionsRequest(target_kc_id="svm", difficulty="intermediate", count=1)]
    assert summary.status is AssessmentStatus.READY
    assert service.list_assessments("student-1", (AssessmentStatus.READY,)) == (summary,)
    assert service.list_assessments("student-2", (AssessmentStatus.READY,)) == ()


def test_open_is_idempotent_and_student_projection_is_answer_blind(lifecycle) -> None:
    service, _generator, clock, summary = lifecycle

    first = service.open(summary.id, "student-1")
    clock.now += timedelta(minutes=5)
    second = service.open(summary.id, "student-1")

    assert first.opened_at == second.opened_at
    assert first.status is AssessmentStatus.IN_PROGRESS
    payload = first.model_dump()
    assert "correct_option_id" not in str(payload)
    assert "explanation" not in str(payload)
    assert "source_ids" not in str(payload)
    assert "sources" not in str(payload)


def test_submit_scores_on_server_uses_server_duration_and_is_idempotent(lifecycle) -> None:
    service, _generator, clock, summary = lifecycle
    assessment = service.open(summary.id, "student-1")
    clock.now += timedelta(seconds=9, milliseconds=250)
    answer = AnswerSubmission(
        question_id=assessment.questions[0].id,
        selected_option_id="B",
        response_time_ms=4100,
        answer_change_count=1,
    )

    first = service.submit(summary.id, "student-1", (answer,))
    clock.now += timedelta(minutes=1)
    second = service.submit(summary.id, "student-1", (answer,))

    assert first == second
    assert first.duration_ms == 9250
    assert first.correct_count == 1
    assert first.score_percent == 100
    assert first.questions[0].correct_option_id == "B"
    assert first.questions[0].sources[0].page == 121


def test_submission_requires_open_complete_unique_answers_and_stable_retries(lifecycle) -> None:
    service, _generator, _clock, summary = lifecycle
    with pytest.raises(AssessmentStateError):
        service.submit(summary.id, "student-1", ())

    assessment = service.open(summary.id, "student-1")
    answer = AnswerSubmission(
        question_id=assessment.questions[0].id,
        selected_option_id="A",
        response_time_ms=100,
    )
    with pytest.raises(AssessmentSubmissionError):
        service.submit(summary.id, "student-1", (answer, answer))

    service.submit(summary.id, "student-1", (answer,))
    changed = answer.model_copy(update={"selected_option_id": "B"})
    with pytest.raises(AssessmentStateError):
        service.submit(summary.id, "student-1", (changed,))


def test_result_is_hidden_before_submission_and_cross_student_access_is_not_found(lifecycle) -> None:
    service, _generator, _clock, summary = lifecycle
    with pytest.raises(AssessmentStateError):
        service.result(summary.id, "student-1")
    with pytest.raises(AssessmentNotFoundError):
        service.get(summary.id, "student-2")
