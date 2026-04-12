import pytest
from fastapi.testclient import TestClient
from apps.api.app.main import app


@pytest.fixture
def client():
    return TestClient(app)
