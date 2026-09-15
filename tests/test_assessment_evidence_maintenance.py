"""Assessment evidence deletion and rebuild contracts."""

from __future__ import annotations

from datetime import datetime, timezone

from ds_course_agent.assessment.application import AssessmentApplicationService
from ds_course_agent.assessment.models import GenerateQuestionsRequest
from ds_course_agent.assessment.records import AnswerSubmission
from ds_course_agent.assessment.repository import AssessmentRepository
from ds_course_agent.teaching.assessment_evidence import AssessmentEvidenceRecorder
from ds_course_agent.teaching.assessment_evidence_maintenance import AssessmentEvidenceMaintenance
from ds_course_agent.teaching.interaction_episode_repository import SQLiteInteractionEpisodeRepository
from ds_course_agent.teaching.learning_event_repository import SQLiteLearningEventRepository
from ds_course_agent.teaching.personalization import EpisodeOutcome, InteractionEpisode
from tests.test_session_learning_loop import FixtureGenerator


def _submit(path, assessment_path, student_id: str):
    events = SQLiteLearningEventRepository(path)
    episodes = SQLiteInteractionEpisodeRepository(path)
    service = AssessmentApplicationService(
        AssessmentRepository(assessment_path),
        FixtureGenerator(),
        submission_recorder=AssessmentEvidenceRecorder(
            event_repository=events,
            episode_repository=episodes,
        ),
    )
    summary = service.assign(student_id, GenerateQuestionsRequest(target_kc_id="pca", count=1))
    active = service.open(summary.id, student_id)
    service.submit(
        summary.id,
        student_id,
        (AnswerSubmission(question_id=active.questions[0].id, selected_option_id="B", response_time_ms=1000),),
    )
    return summary.id, service


def test_delete_is_student_scoped_and_releases_follow_up_links(tmp_path) -> None:
    app_path = tmp_path / "app.db"
    assessment_path = tmp_path / "assessment.db"
    assessment_id, _ = _submit(app_path, assessment_path, "student-1")
    other_assessment_id, _ = _submit(app_path, assessment_path, "student-2")
    episodes = SQLiteInteractionEpisodeRepository(app_path)
    assessment_episode_id = f"assessment_episode:{assessment_id}"
    episodes.save(
        InteractionEpisode(
            episode_id="follow-up",
            student_id="student-1",
            session_id="session",
            turn_id="turn",
            concept_ids=("pca",),
            learner_question="继续解释",
            observed_signals=(),
            inferred_difficulties=(),
            teaching_approach=(),
            outcome=EpisodeOutcome.CONTINUED_CLARIFICATION,
            related_episode_id=assessment_episode_id,
            evidence_event_ids=(),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            extractor_version="test",
        )
    )

    maintenance = AssessmentEvidenceMaintenance(app_path)
    assert maintenance.inspect("student-1", assessment_id).event_count == 1
    maintenance.delete("student-1", assessment_id)
    assert maintenance.inspect("student-1", assessment_id).event_count == 0
    assert episodes.get_for_turn("student-1", "session", "turn").related_episode_id is None
    assert maintenance.inspect("student-2", other_assessment_id).event_count == 1


def test_rebuild_restores_deleted_assessment_evidence(tmp_path) -> None:
    app_path = tmp_path / "app.db"
    assessment_path = tmp_path / "assessment.db"
    assessment_id, service = _submit(app_path, assessment_path, "student-1")
    maintenance = AssessmentEvidenceMaintenance(app_path)
    maintenance.delete("student-1", assessment_id)
    record = AssessmentRepository(assessment_path).get(assessment_id, "student-1")
    assert record is not None

    AssessmentEvidenceRecorder(
        event_repository=SQLiteLearningEventRepository(app_path),
        episode_repository=SQLiteInteractionEpisodeRepository(app_path),
    )(record)

    report = maintenance.inspect("student-1", assessment_id)
    assert report.event_count == 1
    assert report.episode_count == 1
    assert service.result(assessment_id, "student-1").id == assessment_id
