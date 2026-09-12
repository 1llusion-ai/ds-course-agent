"""Integration coverage for the assigned-assessment student API."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from ds_course_agent.api.main import app
from ds_course_agent.api.routers.assessments import get_student_assessment_service
from ds_course_agent.assessment.records import (
    AssessmentResult,
    AssessmentStatus,
    AssessmentSummary,
    StudentAssessment,
)


class StubAssessmentApplicationService:
    """Record student lifecycle calls and return fixed projections."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.now = datetime(2026, 9, 12, 8, 0, tzinfo=timezone.utc)

    def list_assessments(self, student_id: str, statuses: tuple[AssessmentStatus, ...]):
        self.calls.append(("list", student_id, statuses))
        return (
            AssessmentSummary(
                id="assessment-1",
                title="支持向量机测验",
                status=AssessmentStatus.READY,
                question_count=1,
                assigned_at=self.now,
                opened_at=None,
            ),
        )

    def open(self, assessment_id: str, student_id: str) -> StudentAssessment:
        self.calls.append(("open", assessment_id, student_id))
        return self._assessment(AssessmentStatus.IN_PROGRESS)

    def get(self, assessment_id: str, student_id: str) -> StudentAssessment:
        self.calls.append(("get", assessment_id, student_id))
        return self._assessment(AssessmentStatus.IN_PROGRESS)

    def submit(self, assessment_id: str, student_id: str, answers) -> AssessmentResult:
        self.calls.append(("submit", assessment_id, student_id, answers))
        return self._result()

    def result(self, assessment_id: str, student_id: str) -> AssessmentResult:
        self.calls.append(("result", assessment_id, student_id))
        return self._result()

    def _assessment(self, status: AssessmentStatus) -> StudentAssessment:
        return StudentAssessment.model_validate(
            {
                "id": "assessment-1",
                "title": "支持向量机测验",
                "status": status,
                "assigned_at": self.now,
                "opened_at": self.now,
                "questions": [
                    {
                        "id": "question-1",
                        "stem": "支持向量机寻找分类超平面时会最大化什么？",
                        "options": [
                            {"id": "A", "text": "特征数量"},
                            {"id": "B", "text": "类别间隔"},
                            {"id": "C", "text": "聚类数量"},
                            {"id": "D", "text": "样本数量"},
                        ],
                    }
                ],
            }
        )

    def _result(self) -> AssessmentResult:
        return AssessmentResult.model_validate(
            {
                "id": "assessment-1",
                "title": "支持向量机测验",
                "status": "submitted",
                "opened_at": self.now,
                "submitted_at": self.now,
                "duration_ms": 0,
                "correct_count": 1,
                "question_count": 1,
                "score_percent": 100,
                "questions": [
                    {
                        "id": "question-1",
                        "stem": "支持向量机寻找分类超平面时会最大化什么？",
                        "options": [
                            {"id": "A", "text": "特征数量"},
                            {"id": "B", "text": "类别间隔"},
                            {"id": "C", "text": "聚类数量"},
                            {"id": "D", "text": "样本数量"},
                        ],
                        "selected_option_id": "B",
                        "correct_option_id": "B",
                        "is_correct": True,
                        "explanation": "最大间隔提高分类边界的稳健性。",
                        "response_time_ms": 1200,
                        "answer_change_count": 0,
                        "sources": [
                            {
                                "id": "source-1",
                                "text": "最优分类超平面使几何间隔最大。",
                                "source": "数据科学导论",
                                "page": 121,
                            }
                        ],
                    }
                ],
            }
        )


def _override_service(service: StubAssessmentApplicationService) -> None:
    app.dependency_overrides[get_student_assessment_service] = lambda: service


def test_student_lists_assigned_assessments_without_generation_parameters(client: TestClient) -> None:
    service = StubAssessmentApplicationService()
    _override_service(service)
    try:
        response = client.get("/api/assessments", headers={"x-test-student-id": "student-1"})
    finally:
        app.dependency_overrides.pop(get_student_assessment_service, None)

    assert response.status_code == 200
    assert response.json()[0]["question_count"] == 1
    assert service.calls == [("list", "student-1", (AssessmentStatus.READY, AssessmentStatus.IN_PROGRESS))]
    assert client.post("/api/questions/generate", json={"target_kc_id": "svm"}).status_code == 404


def test_active_assessment_projection_never_contains_answers_or_sources(client: TestClient) -> None:
    service = StubAssessmentApplicationService()
    _override_service(service)
    try:
        response = client.post(
            "/api/assessments/assessment-1/open",
            headers={"x-test-student-id": "student-1"},
        )
    finally:
        app.dependency_overrides.pop(get_student_assessment_service, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "in_progress"
    assert payload["questions"][0]["options"][1] == {"id": "B", "text": "类别间隔"}
    serialized = response.text
    assert "correct_option_id" not in serialized
    assert "explanation" not in serialized
    assert "sources" not in serialized


def test_submission_contains_only_answer_telemetry_and_result_reveals_feedback(client: TestClient) -> None:
    service = StubAssessmentApplicationService()
    _override_service(service)
    try:
        response = client.post(
            "/api/assessments/assessment-1/submit",
            headers={"x-test-student-id": "student-1"},
            json={
                "answers": [
                    {
                        "question_id": "question-1",
                        "selected_option_id": "B",
                        "response_time_ms": 1200,
                        "answer_change_count": 0,
                    }
                ]
            },
        )
    finally:
        app.dependency_overrides.pop(get_student_assessment_service, None)

    assert response.status_code == 200
    assert response.json()["questions"][0]["correct_option_id"] == "B"
    assert response.json()["questions"][0]["sources"][0]["page"] == 121
    assert service.calls[0][0:3] == ("submit", "assessment-1", "student-1")


def test_status_filter_is_typed_and_rejects_unknown_values(client: TestClient) -> None:
    service = StubAssessmentApplicationService()
    _override_service(service)
    try:
        valid = client.get(
            "/api/assessments?status=submitted",
            headers={"x-test-student-id": "student-1"},
        )
        invalid = client.get(
            "/api/assessments?status=unknown",
            headers={"x-test-student-id": "student-1"},
        )
    finally:
        app.dependency_overrides.pop(get_student_assessment_service, None)

    assert valid.status_code == 200
    assert service.calls[0] == ("list", "student-1", (AssessmentStatus.SUBMITTED,))
    assert invalid.status_code == 422


def test_real_submission_dependency_updates_profile_without_duplicate_evidence(client, monkeypatch, tmp_path) -> None:
    from tests.test_session_learning_loop import FixtureGenerator, mention

    import ds_course_agent.api.routers.profile as profile_module
    import ds_course_agent.shared.config as config
    import ds_course_agent.teaching.memory_core as memory_module
    from ds_course_agent.assessment.application import AssessmentApplicationService
    from ds_course_agent.assessment.models import GenerateQuestionsRequest
    from ds_course_agent.assessment.repository import AssessmentRepository
    from ds_course_agent.teaching.learning_events import EventType

    memory = memory_module.MemoryCore(str(tmp_path / "history"))
    monkeypatch.setattr(memory_module, "_memory_core", memory)
    monkeypatch.setattr(profile_module, "get_memory", lambda: memory)
    monkeypatch.setattr(config, "ASSESSMENT_DB_PATH", str(tmp_path / "assessments.db"))
    mention(memory, "overfitting")
    service = AssessmentApplicationService(AssessmentRepository(), FixtureGenerator())
    summary = service.assign(
        "student", GenerateQuestionsRequest(target_kc_id="overfitting", count=2), session_id="session"
    )
    headers = {"x-test-student-id": "student"}
    opened = client.post(f"/api/assessments/{summary.id}/open", headers=headers).json()
    payload = {
        "answers": [
            {"question_id": item["id"], "selected_option_id": "B", "response_time_ms": 1000}
            for item in opened["questions"]
        ]
    }
    response = client.post(f"/api/assessments/{summary.id}/submit", headers=headers, json=payload)
    assert response.status_code == 200
    assert response.json()["correct_count"] == 0
    assert response.json()["session_id"] == "session"
    repeat = client.post(f"/api/assessments/{summary.id}/submit", headers=headers, json=payload)
    assert repeat.json() == response.json()
    profile = client.get("/api/profile/detail", headers=headers).json()
    assert profile["practice"][0]["concept_id"] == "overfitting"
    assert profile["practice"][0]["answered_count"] == 2
    assert profile["practice"][0]["level"] == "needs_practice"
    assert len(memory.load_events("student", [EventType.QUESTION_ANSWERED])) == 2
    other = client.get(f"/api/assessments/{summary.id}/result", headers={"x-test-student-id": "other"})
    assert other.status_code == 404
