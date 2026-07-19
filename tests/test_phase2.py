from __future__ import annotations

from datetime import UTC, datetime, timedelta

from harborvision.database import SessionLocal
from harborvision.domain_services import assess_reefer, can_transition_work_order
from harborvision.events import ingest_event
from harborvision.models import (
    Berth,
    Container,
    Incident,
    Organization,
    ReeferReading,
    Terminal,
    VesselCall,
    WorkOrder,
    YardBlock,
    YardSlot,
)
from sqlalchemy import select


def login(client, email: str = "director@harborvision.local", password: str = "HarborVision!2026") -> dict:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()


def test_historical_playback_uses_ordered_events(client, director_headers):
    events = client.get("/api/v1/events?limit=5", headers=director_headers)
    assert events.status_code == 200
    assert events.json()
    occurred = datetime.fromisoformat(events.json()[-1]["occurred_at"])
    start = (occurred - timedelta(hours=1)).isoformat()
    end = (occurred + timedelta(hours=2)).isoformat()
    response = client.get(f"/api/v1/digital-twin/playback?start={start}&end={end}", headers=director_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["reconstruction"] == "nearest persisted snapshot plus ordered operational events"
    assert body["event_count"] >= 1
    assert body["frames"] == sorted(body["frames"], key=lambda frame: frame["at"])


def test_out_of_order_state_event_is_persisted_but_not_applied():
    with SessionLocal() as db:
        org = Organization(name=f"Phase2 Stale Event Org {datetime.now(UTC).timestamp()}")
        db.add(org)
        db.flush()
        terminal = Terminal(organization_id=org.id, name="Stale Event Terminal", code=f"S{org.id}", geometry_json="{}")
        db.add(terminal)
        db.flush()
        block = YardBlock(
            organization_id=org.id,
            terminal_id=terminal.id,
            code="T1",
            kind="general",
            capacity=2,
            max_tier=1,
            x=0,
            y=0,
            width=10,
            height=10,
        )
        db.add(block)
        db.flush()
        first = YardSlot(organization_id=org.id, block_id=block.id, bay=1, row=1, tier=1, occupied=False)
        second = YardSlot(organization_id=org.id, block_id=block.id, bay=2, row=1, tier=1, occupied=False)
        db.add_all([first, second])
        db.flush()
        container = Container(
            organization_id=org.id,
            number=f"AAA U00000{org.id % 10}0".replace(" ", "")[:11],
            iso_type="22G1",
            length_ft=20,
            status="in_yard",
            movement_type="import",
            is_full=True,
            is_hazardous=False,
            is_reefer=False,
            weight_kg=12000,
            dwell_start=datetime.now(UTC),
            last_movement_at=datetime.now(UTC),
        )
        # The event engine does not validate the ISO identifier; registry workflows do.
        db.add(container)
        db.flush()
        newer = datetime.now(UTC)
        applied = ingest_event(
            db,
            org.id,
            "container_yard_move",
            "container",
            str(container.id),
            {"to_slot_id": first.id},
            f"phase2-new-{org.id}",
            newer,
        )
        stale = ingest_event(
            db,
            org.id,
            "container_yard_move",
            "container",
            str(container.id),
            {"to_slot_id": second.id},
            f"phase2-old-{org.id}",
            newer - timedelta(minutes=10),
        )
        db.commit()
        db.refresh(container)
        assert applied.processing_status == "applied"
        assert stale.processing_status == "stale_ignored"
        assert container.slot_id == first.id


def test_placement_analysis_includes_ranked_and_rejected_candidates(client, director_headers):
    item = client.get("/api/v1/containers?limit=1", headers=director_headers).json()["items"][0]
    response = client.get(f"/api/v1/containers/{item['id']}/placement-analysis", headers=director_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["recommendations"]
    assert body["candidate_summary"]["total_slots"] == 960
    assert body["candidate_summary"]["rejected_slots"] > 0
    assert body["method"].startswith("deterministic")


def test_work_order_lifecycle_requires_completion_evidence(client, director_headers):
    with SessionLocal() as db:
        item = WorkOrder(
            organization_id=1,
            title="Phase 2 transition test",
            description="Verify the enforced maintenance workflow.",
            priority="medium",
            status="open",
        )
        db.add(item)
        db.commit()
        work_order_id = item.id
    assert (
        client.post(f"/api/v1/work-orders/{work_order_id}/transition", headers=director_headers, json={"status": "planned"}).status_code
        == 200
    )
    assert (
        client.post(f"/api/v1/work-orders/{work_order_id}/transition", headers=director_headers, json={"status": "in_progress"}).status_code
        == 200
    )
    missing_notes = client.post(f"/api/v1/work-orders/{work_order_id}/transition", headers=director_headers, json={"status": "completed"})
    assert missing_notes.status_code == 422
    completed = client.post(
        f"/api/v1/work-orders/{work_order_id}/transition",
        headers=director_headers,
        json={"status": "completed", "completion_notes": "Cooling circuit inspected and vibration fasteners torqued."},
    )
    assert completed.status_code == 200
    verified = client.post(f"/api/v1/work-orders/{work_order_id}/transition", headers=director_headers, json={"status": "verified"})
    assert verified.status_code == 200
    assert verified.json()["verified_at"]


def test_incident_notes_and_dismissal_reason_are_audited(client):
    with SessionLocal() as db:
        item = Incident(
            organization_id=1,
            title="Phase 2 incident history test",
            incident_type="safety",
            severity="medium",
            status="open",
        )
        db.add(item)
        db.commit()
        incident_id = item.id
    session = login(client, "safety@harborvision.local")
    headers = {"Authorization": f"Bearer {session['access_token']}"}
    note = client.post(
        f"/api/v1/incidents/{incident_id}/notes",
        headers=headers,
        json={"note": "Evidence reviewed against the configured restricted zone."},
    )
    assert note.status_code == 200
    assert client.post(f"/api/v1/incidents/{incident_id}/transition", headers=headers, json={"status": "acknowledged"}).status_code == 200
    assert client.post(f"/api/v1/incidents/{incident_id}/transition", headers=headers, json={"status": "investigating"}).status_code == 200
    missing_reason = client.post(f"/api/v1/incidents/{incident_id}/transition", headers=headers, json={"status": "dismissed"})
    assert missing_reason.status_code == 422
    dismissed = client.post(
        f"/api/v1/incidents/{incident_id}/transition",
        headers=headers,
        json={"status": "dismissed", "dismissed_reason": "Confirmed maintenance crew inside an authorized scheduled window."},
    )
    assert dismissed.status_code == 200
    detail = client.get(f"/api/v1/incidents/{incident_id}", headers=headers).json()
    assert detail["notes"][0]["note"].startswith("Evidence reviewed")
    assert detail["dismissed_reason"]


def test_logout_revokes_refresh_token(client):
    session = login(client)
    headers = {"Authorization": f"Bearer {session['access_token']}"}
    response = client.post("/api/v1/auth/logout", headers=headers, json={"refresh_token": session["refresh_token"]})
    assert response.status_code == 200
    replay = client.post("/api/v1/auth/refresh", json={"refresh_token": session["refresh_token"]})
    assert replay.status_code == 401


def test_simulation_control_state_machine(client, director_headers):
    created = client.post(
        "/api/v1/simulation/runs",
        headers=director_headers,
        json={"scenario": "normal_operations", "speed_multiplier": 8, "random_seed": 20260719},
    )
    assert created.status_code == 200
    run_id = created.json()["id"]
    started = client.post(f"/api/v1/simulation/runs/{run_id}/start", headers=director_headers)
    assert started.json()["status"] == "running"
    paused = client.post(f"/api/v1/simulation/runs/{run_id}/pause", headers=director_headers)
    assert paused.json()["status"] == "paused"
    resumed = client.post(f"/api/v1/simulation/runs/{run_id}/resume", headers=director_headers)
    assert resumed.json()["status"] == "running"
    advanced = client.post(f"/api/v1/simulation/runs/{run_id}/advance", headers=director_headers)
    assert advanced.json()["status"] == "completed"
    assert advanced.json()["event_count"] >= 1


def test_operational_reports_support_pdf_csv_and_json(client, director_headers):
    json_report = client.get("/api/v1/reports/gate-performance/json", headers=director_headers)
    assert json_report.status_code == 200
    assert json_report.json()["row_count"] >= 120
    csv_report = client.get("/api/v1/reports/yard-occupancy/csv", headers=director_headers)
    assert csv_report.status_code == 200
    assert "utilization_pct" in csv_report.text
    pdf_report = client.get("/api/v1/reports/equipment-health/pdf", headers=director_headers)
    assert pdf_report.status_code == 200
    assert pdf_report.content.startswith(b"%PDF")


def test_gate_visit_detail_has_real_stage_metrics(client, director_headers):
    overview = client.get("/api/v1/gates/overview", headers=director_headers).json()
    visit_id = overview["visits"][-1]["id"]
    response = client.get(f"/api/v1/gates/visits/{visit_id}", headers=director_headers)
    assert response.status_code == 200
    body = response.json()
    assert [stage["stage"] for stage in body["timeline"]] == [
        "appointment",
        "arrival",
        "processing_started",
        "processing_completed",
        "exit",
    ]
    assert "turnaround_minutes" in body["metrics"]


def test_berth_assignment_checks_physical_compatibility(client, director_headers):
    now = datetime.now(UTC)
    with SessionLocal() as db:
        terminal_id = db.scalar(select(Terminal.id).where(Terminal.organization_id == 1))
        berth = Berth(
            organization_id=1,
            terminal_id=terminal_id,
            code=f"P2-{int(now.timestamp())}",
            name="Phase 2 Short Berth",
            length_m=180,
            draft_limit_m=9,
            x=0,
            y=0,
            width=10,
            height=10,
        )
        db.add(berth)
        db.flush()
        vessel = VesselCall(
            organization_id=1,
            terminal_id=terminal_id,
            vessel_name="Phase 2 Deep Draft Vessel",
            imo_number=f"IMO-P2-{int(now.timestamp())}",
            voyage_number="P2-001",
            status="approaching",
            vessel_length_m=320,
            draft_m=13,
            eta=now,
            target_moves=500,
            actual_moves=0,
        )
        db.add(vessel)
        db.commit()
        berth_id, vessel_id = berth.id, vessel.id
    response = client.put(
        f"/api/v1/vessels/{vessel_id}/berth-assignment",
        headers=director_headers,
        json={"berth_id": berth_id, "planned_start": now.isoformat(), "planned_end": (now + timedelta(hours=8)).isoformat()},
    )
    assert response.status_code == 409
    codes = {item["code"] for item in response.json()["detail"]["conflicts"]}
    assert {"length_exceeded", "draft_exceeded"}.issubset(codes)


def test_reefer_assessment_explains_duration():
    now = datetime.now(UTC)
    readings = [
        ReeferReading(
            organization_id=1,
            container_id=1,
            recorded_at=now + timedelta(minutes=index * 10),
            target_c=-18,
            actual_c=-14 + index * 0.2,
            power_on=True,
            door_open=False,
            alarm_state="high_temperature",
        )
        for index in range(4)
    ]
    assessment = assess_reefer(readings)
    assert assessment["state"] == "high_temperature"
    assert assessment["duration_minutes"] == 30
    assert "Current temperature" in assessment["explanation"]


def test_work_order_transition_contract():
    assert can_transition_work_order("open", "planned")
    assert not can_transition_work_order("open", "completed")
