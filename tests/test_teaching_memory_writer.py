"""Completed-turn teaching memory persistence contracts."""

from __future__ import annotations

from pathlib import Path

from ds_course_agent.agent.hooks.learning_event import LearningEventHook
from ds_course_agent.assessment.application import AssessmentApplicationService
from ds_course_agent.assessment.models import GenerateQuestionsRequest
from ds_course_agent.assessment.records import AnswerSubmission
from ds_course_agent.assessment.repository import AssessmentRepository
from ds_course_agent.teaching.assessment_evidence import AssessmentEvidenceRecorder
from ds_course_agent.teaching.interaction_episode_repository import SQLiteInteractionEpisodeRepository
from ds_course_agent.teaching.knowledge_mapper import MatchedConcept
from ds_course_agent.teaching.learning_event_repository import SQLiteLearningEventRepository
from ds_course_agent.teaching.teaching_memory_writer import TeachingMemoryWriter
from tests.test_session_learning_loop import FixtureGenerator


def _writer(path: Path) -> TeachingMemoryWriter:
    return TeachingMemoryWriter(SQLiteLearningEventRepository(path), SQLiteInteractionEpisodeRepository(path))


def test_writer_persists_completed_turn_and_is_idempotent(tmp_path) -> None:
    writer = _writer(tmp_path / "app.db")
    hook = LearningEventHook()
    kwargs = {
        "question": "再解释一下 PCA，我还是不懂",
        "session_id": "session-1",
        "student_id": "student-1",
        "turn_id": "turn-1",
        "matched_concepts": [MatchedConcept("pca", "主成分分析", "第7章", "exact", 0.95)],
        "special_case_response": None,
        "learning_event_hook": hook,
        "get_memory_core_fn": lambda: type("Memory", (), {"load_events": lambda self, _student: []})(),
        "classify_question_type_fn": lambda _question: "概念理解",
    }

    assert writer.persist_turn(**kwargs) == 2
    assert writer.persist_turn(**kwargs) == 0
    events = SQLiteLearningEventRepository(tmp_path / "app.db").list_for_student("student-1")
    episodes = SQLiteInteractionEpisodeRepository(tmp_path / "app.db").list_for_student("student-1")
    assert len(events) == 2
    assert len(episodes) == 1
    assert episodes[0].outcome.value == "continued_clarification"


def test_writer_keeps_unknown_outcome_for_plain_completed_question(tmp_path) -> None:
    writer = _writer(tmp_path / "app.db")
    hook = LearningEventHook()
    writer.persist_turn(
        question="什么是 PCA？",
        session_id="session-1",
        student_id="student-1",
        turn_id="turn-1",
        matched_concepts=[MatchedConcept("pca", "主成分分析", "第7章", "exact", 0.95)],
        special_case_response=None,
        learning_event_hook=hook,
        get_memory_core_fn=lambda: type("Memory", (), {"load_events": lambda self, _student: []})(),
        classify_question_type_fn=lambda _question: "概念理解",
    )
    episode = SQLiteInteractionEpisodeRepository(tmp_path / "app.db").list_for_student("student-1")[0]
    assert episode.outcome.value == "unknown"


def test_writer_links_follow_up_episode_to_recent_same_concept(tmp_path) -> None:
    path = tmp_path / "app.db"
    writer = _writer(path)
    hook = LearningEventHook()
    common = {
        "session_id": "session-1",
        "student_id": "student-1",
        "matched_concepts": [MatchedConcept("pca", "主成分分析", "第7章", "exact", 0.95)],
        "special_case_response": None,
        "learning_event_hook": hook,
        "get_memory_core_fn": lambda: type("Memory", (), {"load_events": lambda self, _student: []})(),
        "classify_question_type_fn": lambda _question: "概念理解",
    }
    writer.persist_turn(question="什么是 PCA？", turn_id="turn-1", **common)
    writer.persist_turn(question="我还是不懂，举个例子", turn_id="turn-2", **common)

    episodes = SQLiteInteractionEpisodeRepository(path).list_for_student("student-1", limit=10)
    latest = next(episode for episode in episodes if episode.turn_id == "turn-2")
    first = next(episode for episode in episodes if episode.turn_id == "turn-1")
    assert latest.related_episode_id == first.episode_id
    assert latest.inferred_difficulties == ("example_request",)


def test_writer_links_follow_up_explanation_to_incorrect_assessment(tmp_path) -> None:
    path = tmp_path / "app.db"
    event_repository = SQLiteLearningEventRepository(path)
    episode_repository = SQLiteInteractionEpisodeRepository(path)
    assessment_service = AssessmentApplicationService(
        AssessmentRepository(tmp_path / "assessment.db"),
        FixtureGenerator(),
        submission_recorder=AssessmentEvidenceRecorder(
            event_repository=event_repository,
            episode_repository=episode_repository,
        ),
    )
    summary = assessment_service.assign("student-1", GenerateQuestionsRequest(target_kc_id="pca", count=1))
    active = assessment_service.open(summary.id, "student-1")
    assessment_service.submit(
        summary.id,
        "student-1",
        (AnswerSubmission(question_id=active.questions[0].id, selected_option_id="B", response_time_ms=900),),
    )

    writer = TeachingMemoryWriter(event_repository, episode_repository)
    writer.persist_turn(
        question="解释一下 PCA，我还是不懂",
        session_id="session-1",
        student_id="student-1",
        turn_id="turn-after-assessment",
        matched_concepts=[MatchedConcept("pca", "主成分分析", "第7章", "exact", 0.95)],
        special_case_response=None,
        learning_event_hook=LearningEventHook(),
        get_memory_core_fn=lambda: type("Memory", (), {"load_events": lambda self, _student: []})(),
        classify_question_type_fn=lambda _question: "概念理解",
    )

    episodes = episode_repository.list_for_student("student-1", limit=10)
    follow_up = next(item for item in episodes if item.turn_id == "turn-after-assessment")
    assessment_episode = next(item for item in episodes if item.episode_id.startswith("assessment_episode:"))
    assert assessment_episode.outcome.value == "incorrect_assessment"
    assert follow_up.related_episode_id == assessment_episode.episode_id


def test_writer_reuses_facts_when_projection_retry_follows_partial_failure(tmp_path) -> None:
    path = tmp_path / "app.db"
    event_repository = SQLiteLearningEventRepository(path)
    real_episode_repository = SQLiteInteractionEpisodeRepository(path)

    class FlakyEpisodeRepository:
        def __init__(self) -> None:
            self.failed = False

        def get_for_turn(self, student_id, session_id, turn_id):
            return real_episode_repository.get_for_turn(student_id, session_id, turn_id)

        def list_for_student(self, student_id, **kwargs):
            return real_episode_repository.list_for_student(student_id, **kwargs)

        def save(self, episode):
            if not self.failed:
                self.failed = True
                raise RuntimeError("projection unavailable")
            return real_episode_repository.save(episode)

    writer = TeachingMemoryWriter(event_repository, FlakyEpisodeRepository())
    hook = LearningEventHook()
    kwargs = {
        "question": "解释 PCA",
        "session_id": "session-1",
        "student_id": "student-1",
        "turn_id": "turn-1",
        "matched_concepts": [MatchedConcept("pca", "主成分分析", "第7章", "exact", 0.95)],
        "special_case_response": None,
        "learning_event_hook": hook,
        "get_memory_core_fn": lambda: type("Memory", (), {"load_events": lambda self, _student: []})(),
        "classify_question_type_fn": lambda _question: "概念理解",
    }

    try:
        writer.persist_turn(**kwargs)
    except RuntimeError:
        pass
    assert len(event_repository.list_for_turn("student-1", "session-1", "turn-1")) == 1
    assert writer.persist_turn(**kwargs) == 1
    assert len(event_repository.list_for_turn("student-1", "session-1", "turn-1")) == 1
