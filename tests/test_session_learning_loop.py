"""Closed-loop practice invariants across session selection, scoring, and teaching."""

from __future__ import annotations

from pathlib import Path
from threading import Event

import pytest

from ds_course_agent.agent.hooks.learning_event import LearningEventHook
from ds_course_agent.agent.learning_loop import SessionLearningLoop
from ds_course_agent.agent.routing import (
    EnrichmentPlan,
    ExecutionMode,
    QueryContext,
    RetrievalPolicy,
    RouteDecision,
    RouteExecutionResult,
    RouteFamily,
    RouteIntent,
    RouteState,
)
from ds_course_agent.agent.service import AgentService
from ds_course_agent.agent.turn_runner import collect_turn_result, iter_turn_events
from ds_course_agent.assessment.application import AssessmentApplicationService
from ds_course_agent.assessment.feedback import (
    AssessmentFailureKind,
    AssessmentGenerationProgress,
    QuestionRejection,
    QuestionRejectionCode,
    QuestionSlotFailure,
)
from ds_course_agent.assessment.models import Difficulty, EvidenceSource, GeneratedQuiz, GenerateQuestionsRequest
from ds_course_agent.assessment.preparation import PreparationRepository, PreparationStatus
from ds_course_agent.assessment.records import AnswerSubmission, AssessmentStatus
from ds_course_agent.assessment.repository import AssessmentRepository
from ds_course_agent.assessment.service import AssessmentSlotFailureError
from ds_course_agent.teaching.assessment_assignment import AssessmentAssignmentPlanner
from ds_course_agent.teaching.assessment_evidence import AssessmentEvidenceRecorder
from ds_course_agent.teaching.interaction_episode_repository import SQLiteInteractionEpisodeRepository
from ds_course_agent.teaching.knowledge_mapper import MatchedConcept
from ds_course_agent.teaching.learner_state import SQLiteProfileLearnerStateProvider
from ds_course_agent.teaching.learning_event_repository import SQLiteLearningEventRepository
from ds_course_agent.teaching.learning_events import EventType
from ds_course_agent.teaching.practice import PracticeLevel
from ds_course_agent.teaching.practice_guidance import build_practice_guidance
from ds_course_agent.teaching.profile_snapshot_repository import SQLiteProfileSnapshotRepository
from ds_course_agent.teaching.teaching_memory_writer import TeachingMemoryWriter


class FixtureGenerator:
    """Generate controlled fixtures without invoking retrieval or an LLM."""

    def __init__(self) -> None:
        self.requests: list[GenerateQuestionsRequest] = []
        self.progresses = []

    def generate(self, request: GenerateQuestionsRequest, *, progress=None) -> GeneratedQuiz:
        self.requests.append(request)
        self.progresses.append(progress)
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


def _writer(path: Path) -> TeachingMemoryWriter:
    return TeachingMemoryWriter(
        SQLiteLearningEventRepository(path),
        SQLiteInteractionEpisodeRepository(path),
        SQLiteProfileSnapshotRepository(path),
    )


def mention(
    path: Path,
    concept_id: str,
    *,
    turn_id: str,
    student: str = "student",
    session: str = "session",
) -> None:
    _writer(path).persist_turn(
        question=f"Explain {concept_id}",
        session_id=session,
        student_id=student,
        turn_id=turn_id,
        matched_concepts=[MatchedConcept(concept_id, concept_id, "第8章", "exact", 1.0)],
        special_case_response=None,
        learning_event_hook=LearningEventHook(),
        classify_question_type_fn=lambda _question: "concept_qa",
    )


def submit(service: AssessmentApplicationService, assessment_id: str, option: str = "A"):
    opened = service.open(assessment_id, "student")
    answers = tuple(
        AnswerSubmission(question_id=item.id, selected_option_id=option, response_time_ms=1200)
        for item in opened.questions
    )
    return service.submit(assessment_id, "student", answers), answers


@pytest.mark.parametrize("stream", [False, True], ids=["sync", "stream"])
def test_shared_turn_runner_persists_sqlite_and_schedules_practice(tmp_path, monkeypatch, stream) -> None:
    app_path = tmp_path / "app.db"
    assessment_path = tmp_path / "assessments.db"
    event_repository = SQLiteLearningEventRepository(app_path)
    episode_repository = SQLiteInteractionEpisodeRepository(app_path)
    preparations = PreparationRepository(assessment_path)
    generator = FixtureGenerator()
    assessment_service = AssessmentApplicationService(AssessmentRepository(assessment_path), generator)
    loop = SessionLearningLoop(preparations, assessment_service, event_repository)

    class History:
        def __init__(self) -> None:
            self.messages = []

        def add_messages(self, messages) -> None:
            self.messages.extend(messages)

    def build_state(user_input: str, session_id: str, student_id: str | None = None, **_kwargs) -> RouteState:
        resolved_student_id = student_id or session_id
        return RouteState(
            context=QueryContext(
                original_query=user_input,
                normalized_query=user_input,
                session_id=session_id,
                student_id=resolved_student_id,
                chat_history=[],
            ),
            decision=RouteDecision(
                family=RouteFamily.LEARNING,
                intent=RouteIntent.CONCEPT_QA,
                execution_mode=ExecutionMode.DIRECT_MODEL,
                confidence=1.0,
                retrieval_policy=RetrievalPolicy.OPTIONAL,
                enrichment=EnrichmentPlan(record_learning_event=True),
            ),
            chat_history=[],
            student_id=resolved_student_id,
            session_id=session_id,
            history=History(),
            matched_concepts=[MatchedConcept("pca", "PCA", "第7章", "exact", 0.95)],
            pending_learning_event=True,
        )

    agent = AgentService.__new__(AgentService)
    agent.teaching_memory_writer = TeachingMemoryWriter(event_repository, episode_repository)
    agent.learning_event_hook = LearningEventHook()
    agent.learning_loop = loop
    agent._prepare_query_route = build_state

    result = RouteExecutionResult(
        content="PCA 是一种降维方法。",
        family=RouteFamily.LEARNING,
        intent=RouteIntent.CONCEPT_QA,
        execution_mode=ExecutionMode.DIRECT_MODEL,
    )
    if stream:
        monkeypatch.setattr(
            "ds_course_agent.agent.turn_runner.iter_route_response",
            lambda *_args, **_kwargs: iter(["PCA 是一种降维方法。"]),
        )
    else:
        monkeypatch.setattr("ds_course_agent.agent.turn_runner.execute_route", lambda *_args, **_kwargs: result)

    try:
        completed = collect_turn_result(
            iter_turn_events(agent, "解释 PCA", "session-1", student_id="student-1", stream=stream)
        )
    finally:
        loop.close()

    assert completed.content == result.content
    events = event_repository.list_for_student("student-1", event_types=(EventType.CONCEPT_MENTIONED,))
    assert len(events) == 1
    assert not list(tmp_path.rglob("*.jsonl"))
    jobs = preparations.list_for_student("student-1")
    assert len(jobs) == 1
    assert jobs[0].session_id == "session-1"
    assert jobs[0].request.target_kc_id == "pca"
    assert jobs[0].status is PreparationStatus.READY


def test_session_to_assessment_to_profile_to_next_teaching(tmp_path) -> None:
    app_path = tmp_path / "app.db"
    event_repository = SQLiteLearningEventRepository(app_path)
    episode_repository = SQLiteInteractionEpisodeRepository(app_path)
    generator = FixtureGenerator()
    service = AssessmentApplicationService(
        AssessmentRepository(tmp_path / "assessments.db"),
        generator,
        submission_recorder=AssessmentEvidenceRecorder(
            event_repository=event_repository,
            episode_repository=episode_repository,
        ),
    )
    preparations = PreparationRepository(tmp_path / "assessments.db")
    loop = SessionLearningLoop(
        preparations,
        service,
        event_repository,
        SQLiteProfileLearnerStateProvider(SQLiteProfileSnapshotRepository(app_path)),
    )
    mention(app_path, "overfitting", turn_id="turn-overfitting")
    mention(app_path, "underfitting", turn_id="turn-underfitting")
    mention(app_path, "svm", turn_id="turn-svm", session="another-session")
    mention(app_path, "decision_tree", turn_id="turn-decision-tree", student="another-student")
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
    events = event_repository.list_for_student("student", event_types=(EventType.QUESTION_ANSWERED,))
    assert len(events) == 2
    assert all(record.event.session_id == "session" for record in events)
    assert not event_repository.list_for_student("another-student", event_types=(EventType.QUESTION_ANSWERED,))

    state = SQLiteProfileLearnerStateProvider(SQLiteProfileSnapshotRepository(app_path)).get_state("student")
    assert state.practice["overfitting"].level is PracticeLevel.NEEDS_PRACTICE
    assert state.practice["overfitting"].answered_count == 2
    assert [item.question_stem for item in state.practice["overfitting"].recent_attempts] == [
        "Case 0: which evidence supports this conclusion?",
        "Case 1: which evidence supports this conclusion?",
    ]
    assert all(item.selected_option_text == "Evidence B" for item in state.practice["overfitting"].recent_attempts)
    assert all(item.correct_option_text == "Evidence A" for item in state.practice["overfitting"].recent_attempts)
    assert "underfitting" not in state.practice
    guidance = build_practice_guidance(state, ["overfitting"])
    assert "基础对比例子" in guidance
    assert "Case 0" in guidance
    assert "学生选择“Evidence B”" in guidance
    assert build_practice_guidance(state, ["svm"]) == ""
    missing = build_practice_guidance(state, ["svm"], evidence_requested=True)
    assert "没有已提交的测验作答证据" in missing
    assert "不得声称学生答对、答错、已掌握" in missing


def test_readiness_uses_answers_and_assessment_diversity_not_mentions(tmp_path) -> None:
    app_path = tmp_path / "app.db"
    event_repository = SQLiteLearningEventRepository(app_path)
    episode_repository = SQLiteInteractionEpisodeRepository(app_path)
    for index in range(5):
        mention(app_path, "overfitting", turn_id=f"turn-overfitting-{index}")
    provider = SQLiteProfileLearnerStateProvider(SQLiteProfileSnapshotRepository(app_path))
    planner = AssessmentAssignmentPlanner()
    state = provider.get_state("student")
    assert not state.practice
    assert planner.plan_for_concept("overfitting", state).difficulty is Difficulty.BASIC
    service = AssessmentApplicationService(
        AssessmentRepository(tmp_path / "db"),
        FixtureGenerator(),
        submission_recorder=AssessmentEvidenceRecorder(
            event_repository=event_repository,
            episode_repository=episode_repository,
        ),
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
    app_path = tmp_path / "app.db"
    event_repository = SQLiteLearningEventRepository(app_path)
    episode_repository = SQLiteInteractionEpisodeRepository(app_path)
    recorder = AssessmentEvidenceRecorder(
        event_repository=event_repository,
        episode_repository=episode_repository,
    )
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
    opened = service.open(assessment.id, "student")
    answers = tuple(
        AnswerSubmission(question_id=item.id, selected_option_id="A", response_time_ms=1200)
        for item in opened.questions
    )
    with pytest.raises(OSError):
        service.submit(assessment.id, "student", answers)
    assert service.result(assessment.id, "student").correct_count == 1
    service.submit(assessment.id, "student", answers)
    assert len(event_repository.list_for_student("student", event_types=(EventType.QUESTION_ANSWERED,))) == 1


def test_assessment_recorder_persists_sqlite_evidence_once(tmp_path) -> None:
    app_path = tmp_path / "app.db"
    event_repository = SQLiteLearningEventRepository(app_path)
    episode_repository = SQLiteInteractionEpisodeRepository(app_path)
    recorder = AssessmentEvidenceRecorder(
        event_repository=event_repository,
        episode_repository=episode_repository,
    )
    repository = AssessmentRepository(tmp_path / "db")
    service = AssessmentApplicationService(repository, FixtureGenerator(), submission_recorder=recorder)
    assessment = service.assign("student", GenerateQuestionsRequest(target_kc_id="overfitting", count=1))
    opened = service.open(assessment.id, "student")
    answer = AnswerSubmission(question_id=opened.questions[0].id, selected_option_id="A", response_time_ms=100)
    result = service.submit(assessment.id, "student", (answer,))

    record = repository.get(assessment.id, "student")
    assert record is not None
    recorder(record)
    recorder(record)
    assert service.result(assessment.id, "student") == result
    assert len(event_repository.list_for_student("student", event_types=(EventType.QUESTION_ANSWERED,))) == 1
    assert len(episode_repository.list_for_student("student")) == 1
    assert not list(tmp_path.rglob("*.jsonl"))


def test_failed_preparation_retry_is_owner_scoped_and_reuses_identity(tmp_path) -> None:
    app_path = tmp_path / "app.db"
    mention(app_path, "overfitting", turn_id="turn-overfitting")
    failed = Event()

    class FailOnce(FixtureGenerator):
        def generate(self, request, *, progress=None):
            if not failed.is_set():
                failed.set()
                raise AssessmentSlotFailureError(
                    "one assessment slot failed",
                    slot_failures=(
                        QuestionSlotFailure(
                            slot_index=1,
                            codes=(QuestionRejectionCode.ANSWER_NOT_SUPPORTED,),
                        ),
                    ),
                )
            return super().generate(request, progress=progress)

    generator = FailOnce()
    repository = PreparationRepository(tmp_path / "db")
    service = AssessmentApplicationService(AssessmentRepository(tmp_path / "db"), generator)
    loop = SessionLearningLoop(
        repository,
        service,
        SQLiteLearningEventRepository(app_path),
        SQLiteProfileLearnerStateProvider(SQLiteProfileSnapshotRepository(app_path)),
    )
    loop.schedule("student", "session")
    loop.close()
    job = repository.list_for_student("student")[0]
    assert job.status is PreparationStatus.FAILED
    assert job.failure_kind is AssessmentFailureKind.QUESTION_SLOT_FAILURE
    assert job.failed_slots == (1,)
    assert job.failure_codes == (QuestionRejectionCode.ANSWER_NOT_SUPPORTED,)
    resumed = SessionLearningLoop(
        repository,
        service,
        SQLiteLearningEventRepository(app_path),
        SQLiteProfileLearnerStateProvider(SQLiteProfileSnapshotRepository(app_path)),
    )
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


def test_failed_preparation_persists_progress_and_retry_reuses_it(tmp_path) -> None:
    app_path = tmp_path / "app.db"
    mention(app_path, "overfitting", turn_id="turn-overfitting")
    request = AssessmentAssignmentPlanner().plan_for_concept("overfitting", None, count=2)

    class ProgressAwareGenerator(FixtureGenerator):
        def __init__(self) -> None:
            super().__init__()
            draft = super().generate(request)
            self.progress = AssessmentGenerationProgress.build(
                request,
                title=draft.title,
                evidence=(EvidenceSource(id="textbook", text="Controlled textbook evidence."),),
                accepted_by_slot={0: draft.questions[0]},
                pending_by_slot={
                    1: QuestionRejection(
                        (QuestionRejectionCode.ANSWER_NOT_SUPPORTED,),
                        question=draft.questions[1],
                    )
                },
                repair_round=1,
            )
            self.calls = []
            self.requests.clear()
            self.progresses.clear()

        def generate(self, request: GenerateQuestionsRequest, *, progress=None) -> GeneratedQuiz:
            self.calls.append(progress)
            if progress is None:
                raise AssessmentSlotFailureError(
                    "one assessment slot failed",
                    slot_failures=(
                        QuestionSlotFailure(
                            slot_index=1,
                            codes=(QuestionRejectionCode.ANSWER_NOT_SUPPORTED,),
                        ),
                    ),
                    progress=self.progress,
                )
            return super().generate(request, progress=progress)

    generator = ProgressAwareGenerator()
    repository = PreparationRepository(tmp_path / "db")
    service = AssessmentApplicationService(AssessmentRepository(tmp_path / "db"), generator)
    loop = SessionLearningLoop(
        repository,
        service,
        SQLiteLearningEventRepository(app_path),
        SQLiteProfileLearnerStateProvider(SQLiteProfileSnapshotRepository(app_path)),
    )
    loop.schedule("student", "session")
    loop.close()

    failed = repository.list_for_student("student")[0]
    assert failed.status is PreparationStatus.FAILED
    assert failed.generation_progress == generator.progress
    assert failed.accepted_slot_count == 1
    assert failed.pending_slot_count == 1
    assert failed.retryable is True

    queued = repository.transition(failed, PreparationStatus.QUEUED)
    assert queued is not None
    assert queued.generation_progress == generator.progress
    generating = repository.transition(queued, PreparationStatus.GENERATING)
    assert generating is not None
    assert generating.generation_progress == generator.progress
    failed = repository.transition(
        generating,
        PreparationStatus.FAILED,
        failure_kind=AssessmentFailureKind.QUESTION_SLOT_FAILURE,
        failed_slots=(1,),
        failure_codes=(QuestionRejectionCode.ANSWER_NOT_SUPPORTED,),
        generation_progress=generator.progress,
        retryable=True,
    )
    assert failed is not None

    resumed = SessionLearningLoop(
        repository,
        service,
        SQLiteLearningEventRepository(app_path),
        SQLiteProfileLearnerStateProvider(SQLiteProfileSnapshotRepository(app_path)),
    )
    try:
        resumed.retry(failed.id, "student")
    finally:
        resumed.close()

    ready = repository.get(failed.id, "student")
    assert ready.status is PreparationStatus.READY
    assert ready.generation_progress is None
    assert len(generator.calls) == 2
    assert generator.calls[0] is None
    assert generator.calls[1] == generator.progress
