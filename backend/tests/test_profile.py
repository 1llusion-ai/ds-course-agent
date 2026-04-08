import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_get_profile_summary(client):
    response = client.get("/api/profile/summary/student_001")
    assert response.status_code == 200
    data = response.json()
    assert data["student_id"] == "student_001"
    assert "recent_concepts" in data
    assert "weak_spots" in data


def test_get_profile_detail(client):
    response = client.get("/api/profile/detail/student_001")
    assert response.status_code == 200
    data = response.json()
    assert data["student_id"] == "student_001"
    assert "recent_concepts" in data
    assert "weak_spots" in data
    assert "progress" in data
    assert "chapter_stats" in data
    assert "daily_activity" in data


def test_aggregate_profile(client):
    response = client.post("/api/profile/aggregate/student_001")
    assert response.status_code == 200
    data = response.json()
    assert data["student_id"] == "student_001"
    assert "message" in data
