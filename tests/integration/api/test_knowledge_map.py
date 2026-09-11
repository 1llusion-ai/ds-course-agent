"""The map is private per authenticated learner and needs no LLM initialization."""

from __future__ import annotations

import pytest

from ds_course_agent.api.auth.deps import get_current_student_id
from ds_course_agent.api.core_bridge import get_memory_core
from ds_course_agent.api.main import app
from ds_course_agent.teaching.learning_events import build_concept_mentioned_event
from ds_course_agent.teaching.memory_core import MemoryCore
from ds_course_agent.teaching.profile_models import StudentProfile, WeakSpotCandidate


@pytest.fixture
def map_memory(tmp_path):
    memory = MemoryCore(base_dir=str(tmp_path))

    async def get_test_memory() -> MemoryCore:
        return memory

    app.dependency_overrides[get_memory_core] = get_test_memory
    yield memory
    app.dependency_overrides.pop(get_memory_core, None)


def test_map_uses_authenticated_identity_and_does_not_propagate_related_state(client, map_memory):
    profile = StudentProfile(student_id="alice")
    profile.weak_spot_candidates.append(WeakSpotCandidate(concept_id="missing_values", display_name="缺失值处理"))
    map_memory.save_profile(profile)
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


def test_map_aggregates_new_learning_events_before_overlay(client, map_memory):
    map_memory.record_event(
        build_concept_mentioned_event(
            session_id="session-map",
            student_id="alice",
            concept_id="missing_values",
            concept_name="缺失值处理",
            chapter="第4章",
            question_type="conceptual",
            matched_score=0.95,
            raw_question="缺失值怎么处理？",
        )
    )
    assert map_memory.get_profile("alice").recent_concepts == {}

    response = client.get("/api/knowledge-map", headers={"x-test-student-id": "alice"})

    assert response.status_code == 200
    nodes = {node["canonical_id"]: node for node in response.json()["nodes"]}
    assert nodes["missing_values"]["learning_state"] == "recent"
