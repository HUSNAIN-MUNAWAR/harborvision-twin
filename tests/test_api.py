from __future__ import annotations

import shutil

import pytest
from harborvision.database import SessionLocal
from harborvision.models import Organization, User
from harborvision.security import hash_password


def login(client, email="director@harborvision.local", password="HarborVision!2026"):
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()


def test_login_and_refresh_rotation(client):
    session = login(client)
    assert session["access_token"]
    assert session["refresh_token"]
    rotated = client.post("/api/v1/auth/refresh", json={"refresh_token": session["refresh_token"]})
    assert rotated.status_code == 200
    assert rotated.json()["refresh_token"] != session["refresh_token"]
    replay = client.post("/api/v1/auth/refresh", json={"refresh_token": session["refresh_token"]})
    assert replay.status_code == 401


def test_dashboard_and_digital_twin_are_database_backed(client, director_headers):
    dashboard = client.get("/api/v1/dashboard", headers=director_headers)
    assert dashboard.status_code == 200
    data = dashboard.json()
    assert data["kpis"]["container_registry"] == 600
    assert data["kpis"]["yard_occupancy_pct"] > 50
    twin = client.get("/api/v1/digital-twin/state", headers=director_headers)
    assert twin.status_code == 200
    assert len(twin.json()["yard_blocks"]) == 8
    assert len(twin.json()["equipment"]) == 20


def test_container_search_detail_and_recommendation(client, director_headers):
    search = client.get("/api/v1/containers?q=MSCU&limit=5", headers=director_headers)
    assert search.status_code == 200
    item = search.json()["items"][0]
    assert item["validation"]["valid"] is True
    detail = client.get(f"/api/v1/containers/{item['id']}", headers=director_headers)
    assert detail.status_code == 200
    assert detail.json()["location"]["block"]
    recommendations = client.get(f"/api/v1/containers/{item['id']}/recommendations", headers=director_headers)
    assert recommendations.status_code == 200
    assert recommendations.json()
    assert "explanation" in recommendations.json()[0]


def test_organization_isolation(client):
    with SessionLocal() as db:
        other = Organization(name="Isolated Test Organization")
        db.add(other)
        db.flush()
        db.add(
            User(
                organization_id=other.id,
                email="isolated@example.test",
                full_name="Isolated User",
                role="director",
                password_hash=hash_password("Isolated!2026"),
            )
        )
        db.commit()
    session = login(client, "isolated@example.test", "Isolated!2026")
    headers = {"Authorization": f"Bearer {session['access_token']}"}
    containers = client.get("/api/v1/containers", headers=headers)
    assert containers.status_code == 200
    assert containers.json()["total"] == 0


def test_berth_conflict_detection(client):
    session = login(client, "planner@harborvision.local")
    headers = {"Authorization": f"Bearer {session['access_token']}"}
    vessels = client.get("/api/v1/vessels", headers=headers).json()
    occupied = vessels[0]
    target = vessels[1]
    response = client.put(
        f"/api/v1/vessels/{target['id']}/berth-assignment",
        headers=headers,
        json={"berth_id": occupied["berth_id"], "planned_start": occupied["planned_start"], "planned_end": occupied["planned_end"]},
    )
    assert response.status_code == 409


def test_incident_transition_rules(client):
    session = login(client, "safety@harborvision.local")
    headers = {"Authorization": f"Bearer {session['access_token']}"}
    incidents = client.get("/api/v1/incidents", headers=headers).json()
    incident = next(i for i in incidents if i["status"] == "investigating")
    resolved = client.post(
        f"/api/v1/incidents/{incident['id']}/transition",
        headers=headers,
        json={"status": "resolved", "corrective_action": "Opened additional lane", "root_cause": "Arrival surge"},
    )
    assert resolved.status_code == 200
    invalid = client.post(f"/api/v1/incidents/{incident['id']}/transition", headers=headers, json={"status": "acknowledged"})
    assert invalid.status_code == 409


def test_simulation_changes_gate_state(client, director_headers):
    before = client.get("/api/v1/gates/overview", headers=director_headers).json()["queue_length"]
    result = client.post("/api/v1/simulation/run", headers=director_headers, json={"scenario": "gate_congestion", "speed_multiplier": 10})
    assert result.status_code == 200
    assert result.json()["events_created"] == 18
    after = client.get("/api/v1/gates/overview", headers=director_headers).json()["queue_length"]
    assert after >= before + 18


def test_ocr_pipeline_returns_valid_iso_candidate(client, director_headers):
    if shutil.which("tesseract") is None:
        pytest.skip("Tesseract OCR binary is required for this integration test")
    response = client.post("/api/v1/ocr/process-sample", headers=director_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["normalized_number"] == "MSCU1000001"
    assert data["validation_status"] == "valid"
    assert data["confidence"] > 0.7


def test_video_pipeline_persists_real_safety_event(client, director_headers):
    response = client.post("/api/v1/vision/process-sample", headers=director_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["frames_processed"] == 150
    assert data["events_created"] >= 1
    events = client.get("/api/v1/safety-events", headers=director_headers).json()
    assert events[0]["event_type"] == "restricted_zone_intrusion"
    assert events[0]["evidence_path"].endswith(".jpg")


def test_reports_generate_real_files(client, director_headers):
    pdf = client.get("/api/v1/reports/daily.pdf", headers=director_headers)
    assert pdf.status_code == 200
    assert pdf.headers["content-type"].startswith("application/pdf")
    assert pdf.content.startswith(b"%PDF")
    csv = client.get("/api/v1/reports/containers.csv", headers=director_headers)
    assert csv.status_code == 200
    assert "MSCU1000001" in csv.text
