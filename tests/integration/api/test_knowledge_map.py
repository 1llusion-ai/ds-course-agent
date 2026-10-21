"""The map is private per authenticated learner and needs no LLM initialization."""

from __future__ import annotations

from dataclasses import replace

import pytest

from ds_course_agent.api.auth.deps import get_current_student_id
from ds_course_agent.api.core_bridge import get_memory_core
from ds_course_agent.api.course_context import course_catalog
from ds_course_agent.api.main import app
from ds_course_agent.courses import CourseCatalog, CourseId
from ds_course_agent.teaching.learning_event_repository import LearningEventRecord, SQLiteLearningEventRepository
from ds_course_agent.teaching.learning_events import build_concept_mentioned_event, build_misconception_event
from ds_course_agent.teaching.profile_snapshot_repository import (
    SQLiteProfileReadService,
    SQLiteProfileSnapshotRepository,
)


@pytest.fixture
def map_events(tmp_path):
    return SQLiteLearningEventRepository(tmp_path / "map.db")


@pytest.fixture
def map_memory(tmp_path):
    memory = SQLiteProfileReadService(SQLiteProfileSnapshotRepository(tmp_path / "map.db"))

    async def get_test_memory() -> SQLiteProfileReadService:
        return memory

    app.dependency_overrides[get_memory_core] = get_test_memory
    yield memory
    app.dependency_overrides.pop(get_memory_core, None)


def test_map_uses_authenticated_identity_and_does_not_propagate_related_state(client, map_memory, map_events):
    event = build_misconception_event(
        session_id="session-map",
        student_id="alice",
        concept_id="missing_values",
        misconception_text="缺失值总应该直接删除",
        correct_answer="应根据缺失机制和任务选择处理方法",
        misconception_type="overgeneralization",
        severity="medium",
        target_bucket="weakness",
    )
    map_events.append(LearningEventRecord(event, "turn-map"))
    response = client.get("/api/knowledge-map?student_id=bob", headers={"x-test-student-id": "alice"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    nodes = {node["canonical_id"]: node for node in response.json()["nodes"]}
    assert nodes["missing_values"]["learning_state"] == "needs_review"
    assert "pandas_fillna" not in nodes
    assert nodes["data_cleaning"]["learning_state"] == "unobserved"
    assert nodes["missing_values"]["learning_points"][0]["sources"][0]["book_page"] == 65
    other = client.get("/api/knowledge-map", headers={"x-test-student-id": "bob"}).json()
    assert all(node["learning_state"] == "unobserved" for node in other["nodes"])


def test_map_requires_real_cookie_authentication(client, map_memory):
    override = app.dependency_overrides.pop(get_current_student_id)
    try:
        response = client.get("/api/knowledge-map?student_id=alice")
        assert response.status_code == 401
    finally:
        app.dependency_overrides[get_current_student_id] = override


def test_map_aggregates_new_learning_events_before_overlay(client, map_memory, map_events):
    assert map_memory.get_profile("alice").recent_concepts == {}
    map_events.append(
        LearningEventRecord(
            build_concept_mentioned_event(
                session_id="session-map",
                student_id="alice",
                concept_id="missing_values",
                concept_name="缺失值处理",
                chapter="第4章",
                question_type="conceptual",
                matched_score=0.95,
                raw_question="缺失值怎么处理？",
            ),
            "turn-map",
        )
    )

    response = client.get("/api/knowledge-map", headers={"x-test-student-id": "alice"})

    assert response.status_code == 200
    nodes = {node["canonical_id"]: node for node in response.json()["nodes"]}
    assert nodes["missing_values"]["learning_state"] == "recent"


def test_digital_literacy_graph_shows_only_its_own_course_nodes(client, map_memory):
    response = client.get("/api/knowledge-map?course_id=digital-literacy", headers={"x-test-student-id": "alice"})

    assert response.status_code == 200
    assert response.json()["course_name"] == "数字素养与技能导论"
    assert len(response.json()["chapters"]) == 8
    assert response.json()["nodes"]
    assert response.json()["edges"]
    assert any(node["canonical_id"] == "dl_5_4_4" for node in response.json()["nodes"])
    assert all(node["canonical_id"].startswith(("dl_", "chapter:")) for node in response.json()["nodes"])


@pytest.mark.parametrize("course_id", ["unknown-course", "../../bad"])
def test_map_rejects_unknown_or_invalid_course(client, map_memory, course_id):
    response = client.get("/api/knowledge-map", params={"course_id": course_id})

    assert response.status_code == 422


@pytest.mark.parametrize("event_course", ["data-science-intro", "digital-literacy"])
def test_map_learning_state_is_isolated_even_for_shared_concept_ids(
    client, map_memory, map_events, monkeypatch, event_course
):
    import ds_course_agent.api.course_context as context_module

    default = course_catalog().require("data-science-intro")
    manifests = tuple(
        replace(course, knowledge_graph_path=default.knowledge_graph_path, toc_path=default.toc_path)
        if course.course_id == "digital-literacy"
        else course
        for course in course_catalog().list()
    )
    monkeypatch.setattr(context_module, "course_catalog", lambda: CourseCatalog(manifests))
    event = build_concept_mentioned_event(
        session_id="shared-session",
        student_id="alice",
        concept_id="missing_values",
        concept_name="缺失值处理",
        chapter="第4章",
        question_type="conceptual",
        matched_score=0.95,
        raw_question="缺失值怎么处理？",
    )
    event.course_id = CourseId(event_course)
    map_events.append(LearningEventRecord(event, "turn-map"))

    for course_id in ("data-science-intro", "digital-literacy", "data-science-intro"):
        response = client.get(
            "/api/knowledge-map", params={"course_id": course_id}, headers={"x-test-student-id": "alice"}
        )
        assert response.status_code == 200
        node = next(item for item in response.json()["nodes"] if item["canonical_id"] == "missing_values")
        assert node["learning_state"] == ("recent" if course_id == event_course else "unobserved")
