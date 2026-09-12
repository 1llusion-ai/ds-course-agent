"""Closed-loop practice invariants across session selection, scoring, and teaching."""

from __future__ import annotations

from threading import Event

import pytest

from ds_course_agent.agent.learning_loop import SessionLearningLoop
from ds_course_agent.assessment.application import AssessmentApplicationService
from ds_course_agent.assessment.models import Difficulty, GeneratedQuiz, GenerateQuestionsRequest
from ds_course_agent.assessment.preparation import PreparationRepository, PreparationStatus
from ds_course_agent.assessment.records import AnswerSubmission, AssessmentStatus
from ds_course_agent.assessment.repository import AssessmentRepository
from ds_course_agent.teaching.assessment_assignment import AssessmentAssignmentPlanner
from ds_course_agent.teaching.assessment_evidence import AssessmentEvidenceRecorder
from ds_course_agent.teaching.learner_state import RuleBasedLearnerStateProvider
from ds_course_agent.teaching.learning_events import EventType, build_concept_mentioned_event
from ds_course_agent.teaching.memory_core import MemoryCore
from ds_course_agent.teaching.practice import PracticeLevel
from ds_course_agent.teaching.practice_guidance import build_practice_guidance


class FixtureGenerator:
    """Generate controlled fixtures without invoking retrieval or an LLM."""

    def __init__(self) -> None:
        self.requests: list[GenerateQuestionsRequest] = []

    def generate(self, request: GenerateQuestionsRequest) -> GeneratedQuiz:
        self.requests.append(request)
        return GeneratedQuiz.model_validate(
            {
                "title": f"{request.target_kc_id} practice",
                "questions": [
                    {
                        "stem": f"Case {index}: which evidence supports this conclusion?",
                        "options": [{"id": label, "text": f"Evidence {label}"} for label in "ABCD"],
                        "correct_option_id": "A",
                        "explanation": "Independent validation supports the conclusion.",
                        "difficulty": request.difficulty,
                        "source_ids": ["textbook"],
                    }
                    for index in range(request.count)
                ],
                "sources": [{"id": "textbook", "text": "Controlled textbook evidence."}],
            }
        )


def mention(memory: MemoryCore, concept_id: str, *, student: str = "student", session: str = "session") -> None:
    memory.record_event(
        build_concept_mentioned_event(
            session, student, concept_id, concept_id, "第8章", "concept_qa", 1.0, f"Explain {concept_id}"
        )
    )


def submit(service: AssessmentApplicationService, assessment_id: str, option: str = "A"):
    opened = service.open(assessment_id, "student")
    answers = tuple(
        AnswerSubmission(question_id=item.id, selected_option_id=option, response_time_ms=1200)
        for item in opened.questions
    )
    return service.submit(assessment_id, "student", answers), answers


def test_session_to_assessment_to_profile_to_next_teaching(tmp_path) -> None:
    memory = MemoryCore(str(tmp_path / "history"))
    generator = FixtureGenerator()
    service = AssessmentApplicationService(
        AssessmentRepository(tmp_path / "assessments.db"),
        generator,
        submission_recorder=AssessmentEvidenceRecorder(lambda: memory),
    )
    preparations = PreparationRepository(tmp_path / "assessments.db")
    loop = SessionLearningLoop(preparations, service, lambda: memory)
    mention(memory, "overfitting")
    mention(memory, "underfitting")
    mention(memory, "svm", session="another-session")
    mention(memory, "decision_tree", student="another-student")
    try:
        loop.schedule("student", "session")
        loop.schedule("student", "session")
    finally:
        loop.close()
    assert {request.target_kc_id for request in generator.requests} == {"overfitting", "underfitting"}
    assert len(generator.requests) == 2
    assert all(job.status is PreparationStatus.READY for job in loop.list_preparations("student"))
    assessments = service.list_assessments("student", (AssessmentStatus.READY,))
    assert len(assessments) == 2
    assert all(item.session_id == "session" for item in assessments)
    target = next(item for item in assessments if "overfitting" in item.title)
    opened = service.open(target.id, "student")
    assert "correct_option_id" not in opened.model_dump_json()
    result, answers = submit(service, target.id, option="B")
    assert result.correct_count == 0
    assert service.submit(target.id, "student", answers) == result
    assert service.result(target.id, "student") == result
    events = memory.load_events("student", [EventType.QUESTION_ANSWERED])
    assert len(events) == 2
    assert all(event.session_id == "session" for event in events)
    assert not memory.load_events("another-student", [EventType.QUESTION_ANSWERED])

    fresh_memory = MemoryCore(str(tmp_path / "history"))
    state = RuleBasedLearnerStateProvider(lambda: fresh_memory).get_state("student")
    assert state.practice["overfitting"].level is PracticeLevel.NEEDS_PRACTICE
    assert state.practice["overfitting"].answered_count == 2
    assert "underfitting" not in state.practice
    assert "基础对比例子" in build_practice_guidance(state, ["overfitting"])
    assert build_practice_guidance(state, ["svm"]) == ""


def test_readiness_uses_answers_and_assessment_diversity_not_mentions(tmp_path) -> None:
    memory = MemoryCore(str(tmp_path / "history"))
    for _ in range(5):
        mention(memory, "overfitting")
    provider = RuleBasedLearnerStateProvider(lambda: memory)
    planner = AssessmentAssignmentPlanner()
    state = provider.get_state("student")
    assert not state.practice
    assert planner.plan_for_concept("overfitting", state).difficulty is Difficulty.BASIC
    service = AssessmentApplicationService(
        AssessmentRepository(tmp_path / "db"),
        FixtureGenerator(),
        submission_recorder=AssessmentEvidenceRecorder(lambda: memory),
    )
    first = service.assign("student", GenerateQuestionsRequest(target_kc_id="overfitting", count=2))
    submit(service, first.id)
    state = provider.get_state("student")
    assert state.practice["overfitting"].level is PracticeLevel.PRACTICED
    next_request = planner.plan_for_concept("overfitting", state, count=2)
    assert next_request.difficulty is Difficulty.INTERMEDIATE
    second = service.assign("student", next_request)
    submit(service, second.id)
    state = provider.get_state("student")
    assert state.practice["overfitting"].level is PracticeLevel.READY_FOR_EXTENSION
    assert "迁移应用" in build_practice_guidance(state, ["overfitting"])
    assert planner.plan_for_concept("overfitting", state).difficulty is Difficulty.ADVANCED
    third = service.assign("student", next_request)
    submit(service, third.id, "B")
    state = provider.get_state("student")
    assert state.practice["overfitting"].level is PracticeLevel.NEEDS_PRACTICE


def test_saved_submission_recovers_evidence_after_recorder_failure(tmp_path) -> None:
    memory = MemoryCore(str(tmp_path / "history"))
    recorder = AssessmentEvidenceRecorder(lambda: memory)
    fail = True

    def interrupted(record):
        nonlocal fail
        if fail:
            fail = False
            raise OSError("temporary event-store failure")
        recorder(record)

    service = AssessmentApplicationService(
        AssessmentRepository(tmp_path / "db"),
        FixtureGenerator(),
        submission_recorder=interrupted,
    )
    assessment = service.assign("student", GenerateQuestionsRequest(target_kc_id="overfitting", count=1))
    with pytest.raises(OSError):
        submit(service, assessment.id)
    assert service.result(assessment.id, "student").correct_count == 1
    service.result(assessment.id, "student")
    assert len(memory.load_events("student", [EventType.QUESTION_ANSWERED])) == 1


def test_failed_preparation_retry_is_owner_scoped_and_reuses_identity(tmp_path) -> None:
    memory = MemoryCore(str(tmp_path / "history"))
    mention(memory, "overfitting")
    failed = Event()

    class FailOnce(FixtureGenerator):
        def generate(self, request):
            if not failed.is_set():
                failed.set()
                raise RuntimeError("fixture generation failure")
            return super().generate(request)

    generator = FailOnce()
    repository = PreparationRepository(tmp_path / "db")
    service = AssessmentApplicationService(AssessmentRepository(tmp_path / "db"), generator)
    loop = SessionLearningLoop(repository, service, lambda: memory)
    loop.schedule("student", "session")
    loop.close()
    job = repository.list_for_student("student")[0]
    assert job.status is PreparationStatus.FAILED
    resumed = SessionLearningLoop(repository, service, lambda: memory)
    try:
        with pytest.raises(KeyError):
            resumed.retry(job.id, "another-student")
        resumed.retry(job.id, "student")
    finally:
        resumed.close()
    result = repository.get(job.id, "student")
    assert result.status is PreparationStatus.READY
    assert result.assessment_id == job.id
    assert len(generator.requests) == 1
