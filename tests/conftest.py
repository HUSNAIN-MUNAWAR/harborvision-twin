from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from harborvision.main import app
from harborvision.seed import seed_database


@pytest.fixture(scope="session", autouse=True)
def seeded_database():
    seed_database(reset=True)
    yield


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def director_headers(client):
    response = client.post("/api/v1/auth/login", json={"email": "director@harborvision.local", "password": "HarborVision!2026"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
