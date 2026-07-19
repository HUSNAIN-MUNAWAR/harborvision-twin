from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta

from .algorithms import make_container_number
from .config import ROOT
from .database import Base, SessionLocal, engine
from .models import (
    AuditLog,
    Berth,
    Camera,
    CameraZone,
    Container,
    ContainerMovement,
    Equipment,
    EquipmentTelemetry,
    GateLane,
    Incident,
    OperationalEvent,
    Organization,
    ReeferReading,
    Terminal,
    TruckVisit,
    TwinSnapshot,
    User,
    VesselCall,
    WorkOrder,
    YardBlock,
    YardSlot,
)
from .security import hash_password
from .vision import generate_container_image, generate_sample_video

DEMO_PASSWORD = "HarborVision!2026"


def reset_database() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def seed_database(reset: bool = True) -> dict:
    if reset:
        reset_database()
    now = datetime.now(UTC).replace(microsecond=0)
    db = SessionLocal()
    try:
        organization = Organization(name="HarborVision Demonstration Authority")
        db.add(organization)
        db.flush()
        terminal_geometry = {
            "coordinate_system": "NorthStar Local Grid (metres)",
            "extent": [0, 0, 1200, 700],
            "origin": "south-west terminal boundary",
        }
        terminal = Terminal(
            organization_id=organization.id, name="NorthStar Container Terminal", code="NST", geometry_json=json.dumps(terminal_geometry)
        )
        db.add(terminal)
        db.flush()

        users = [
            ("admin@harborvision.local", "System Administrator", "admin"),
            ("director@harborvision.local", "Port Operations Director", "director"),
            ("planner@harborvision.local", "Berth Planner", "planner"),
            ("yard@harborvision.local", "Yard Controller", "yard"),
            ("safety@harborvision.local", "Safety Officer", "safety"),
            ("analyst@harborvision.local", "Operations Analyst", "analyst"),
        ]
        password_hash = hash_password(DEMO_PASSWORD)
        for email, name, role in users:
            db.add(User(organization_id=organization.id, email=email, full_name=name, role=role, password_hash=password_hash))

        berth_codes = ["A1", "A2", "B1", "B2"]
        berths: list[Berth] = []
        for idx, code in enumerate(berth_codes):
            berth = Berth(
                organization_id=organization.id,
                terminal_id=terminal.id,
                code=code,
                name=f"Berth {code}",
                length_m=360 + (idx % 2) * 40,
                x=75 + idx * 270,
                y=45,
                width=230,
                height=55,
            )
            db.add(berth)
            berths.append(berth)
        db.flush()

        vessels: list[VesselCall] = []
        vessel_names = [
            "MV Aurora Meridian",
            "MV Pacific Kestrel",
            "MV Atlas Horizon",
            "MV Coral Vanguard",
            "MV Baltic Arrow",
            "MV Ocean Helix",
        ]
        for idx, name in enumerate(vessel_names):
            start = now + timedelta(hours=(idx - 2) * 14)
            status = ["departed", "departed", "berthed", "operations", "approaching", "scheduled"][idx]
            vessel = VesselCall(
                organization_id=organization.id,
                terminal_id=terminal.id,
                berth_id=berths[idx % 4].id,
                vessel_name=name,
                imo_number=f"IMO9{200100 + idx}",
                voyage_number=f"NS{2600 + idx}",
                status=status,
                eta=start - timedelta(hours=2),
                planned_start=start,
                planned_end=start + timedelta(hours=18 + idx),
                actual_arrival=start + timedelta(minutes=(idx - 2) * 18) if idx < 4 else None,
                actual_departure=start + timedelta(hours=17 + idx) if idx < 2 else None,
                target_moves=640 + idx * 75,
                actual_moves=(640 + idx * 75) if idx < 2 else 310 + idx * 45,
                x=berths[idx % 4].x + 75,
                y=110 if idx in (2, 3) else 18,
            )
            db.add(vessel)
            vessels.append(vessel)
        db.flush()

        block_specs = [
            ("Y01", "general", 150, 170),
            ("Y02", "general", 390, 170),
            ("Y03", "general", 630, 170),
            ("Y04", "general", 870, 170),
            ("Y05", "general", 150, 390),
            ("Y06", "general", 390, 390),
            ("R1", "reefer", 630, 390),
            ("H1", "hazardous", 870, 390),
        ]
        blocks: list[YardBlock] = []
        all_slots: list[YardSlot] = []
        for code, kind, x, y in block_specs:
            block = YardBlock(
                organization_id=organization.id,
                terminal_id=terminal.id,
                code=code,
                kind=kind,
                capacity=120,
                max_tier=4,
                x=x,
                y=y,
                width=180,
                height=135,
            )
            db.add(block)
            db.flush()
            blocks.append(block)
            for bay in range(1, 6):
                for row in range(1, 7):
                    for tier in range(1, 5):
                        slot = YardSlot(organization_id=organization.id, block_id=block.id, bay=bay, row=row, tier=tier, occupied=False)
                        db.add(slot)
                        all_slots.append(slot)
        db.flush()

        prefixes = ["MSCU", "MAEU", "TGHU", "CMAU", "HLCU", "OOLU", "COSU", "TEMU"]
        containers: list[Container] = []
        for idx in range(600):
            serial = f"{100000 + idx:06d}"
            number = make_container_number(prefixes[idx % len(prefixes)] + serial)
            reefer = idx % 17 == 0
            hazardous = idx % 43 == 0 and not reefer
            desired_kind = "reefer" if reefer else "hazardous" if hazardous else "general"
            eligible = [s for s in all_slots if next(b for b in blocks if b.id == s.block_id).kind == desired_kind and not s.occupied]
            slot = eligible[(idx * 7) % len(eligible)]
            slot.occupied = True
            dwell_days = (idx * 13) % 28
            container = Container(
                organization_id=organization.id,
                number=number,
                iso_type="45R1" if reefer else ("42G1" if idx % 3 else "22G1"),
                length_ft=40 if idx % 3 else 20,
                status="in_yard",
                movement_type=["import", "export", "transshipment"][idx % 3],
                is_full=idx % 7 != 0,
                is_hazardous=hazardous,
                is_reefer=reefer,
                weight_kg=3500 + (idx * 271) % 24000,
                slot_id=slot.id,
                vessel_call_id=vessels[idx % len(vessels)].id,
                dwell_start=now - timedelta(days=dwell_days, hours=idx % 24),
                last_movement_at=now - timedelta(hours=(idx * 5) % 120),
                seal_status="sealed" if idx % 19 else "inspection",
                damage_status="clear" if idx % 37 else "minor",
            )
            db.add(container)
            containers.append(container)
        db.flush()
        for container in containers[:180]:
            db.add(
                ContainerMovement(
                    organization_id=organization.id,
                    container_id=container.id,
                    from_slot_id=None,
                    to_slot_id=container.slot_id,
                    movement_type="container_placed",
                    occurred_at=container.last_movement_at,
                    source_event_id=f"seed-{container.id}",
                )
            )

        lanes: list[GateLane] = []
        for idx in range(6):
            lane = GateLane(
                organization_id=organization.id,
                terminal_id=terminal.id,
                code=f"G{idx + 1}",
                direction="inbound" if idx < 3 else "outbound",
                is_open=idx != 5,
                x=1040 + (idx % 3) * 32,
                y=540 + (idx // 3) * 48,
            )
            db.add(lane)
            lanes.append(lane)
        db.flush()
        for idx in range(120):
            arrival = now - timedelta(minutes=(119 - idx) * 9)
            queue_delay = 6 + (idx % 7) * 2 + (18 if idx > 108 else 0)
            service = 7 + (idx % 5)
            status = "queued" if idx >= 114 else "processing" if idx >= 110 else "completed"
            processing_start: datetime | None = arrival + timedelta(minutes=queue_delay) if status != "queued" else None
            processing_end: datetime | None = (
                processing_start + timedelta(minutes=service) if processing_start and status == "completed" else None
            )
            exit_at = processing_end + timedelta(minutes=2) if processing_end else None
            db.add(
                TruckVisit(
                    organization_id=organization.id,
                    lane_id=lanes[idx % len(lanes)].id,
                    container_id=containers[(idx * 3) % len(containers)].id,
                    plate_number=f"ICT-{1000 + idx}",
                    driver_name=f"Driver {idx + 1:03d}",
                    status=status,
                    appointment_at=arrival - timedelta(minutes=(idx % 4) * 8),
                    arrival_at=arrival,
                    processing_start=processing_start,
                    processing_end=processing_end,
                    exit_at=exit_at,
                )
            )

        equipment: list[Equipment] = []
        types = ["STS Crane"] * 8 + ["RTG Crane"] * 6 + ["Reach Stacker"] * 3 + ["Terminal Tractor"] * 3
        for idx, equipment_type in enumerate(types):
            equipment_item = Equipment(
                organization_id=organization.id,
                terminal_id=terminal.id,
                code=f"EQ-{idx + 1:03d}",
                name=f"{equipment_type} {idx + 1}",
                equipment_type=equipment_type,
                state="maintenance" if idx == 5 else "operating" if idx % 4 != 0 else "idle",
                availability=0.72 if idx == 5 else round(0.91 + (idx % 7) * 0.01, 2),
                x=110 + (idx % 8) * 120,
                y=135 if idx < 8 else 335 + (idx % 3) * 75,
                last_service_at=now - timedelta(days=18 + idx * 2),
            )
            db.add(equipment_item)
            equipment.append(equipment_item)
        db.flush()
        for equipment_index, equipment_item in enumerate(equipment):
            for reading_index in range(360):
                recorded = now - timedelta(hours=(359 - reading_index) * 2)
                hour = recorded.hour
                shift_load = 65 + 20 * math.sin((hour / 24) * 2 * math.pi) + (equipment_index % 4) * 3
                temperature = 54 + shift_load * 0.18 + 1.2 * math.sin(reading_index / 9)
                vibration = 2.0 + shift_load * 0.018 + 0.2 * math.sin(reading_index / 6)
                if equipment_index == 5 and reading_index > 325:
                    ramp = (reading_index - 325) / 35
                    temperature += ramp * 18
                    vibration += ramp * 3.5
                hydraulic = 190 + shift_load * 0.35 + 3 * math.sin(reading_index / 5)
                db.add(
                    EquipmentTelemetry(
                        organization_id=organization.id,
                        equipment_id=equipment_item.id,
                        recorded_at=recorded,
                        temperature_c=round(temperature, 2),
                        vibration_mm_s=round(vibration, 3),
                        hydraulic_bar=round(hydraulic, 2),
                        load_pct=round(max(0, min(100, shift_load)), 2),
                        anomaly_score=0,
                    )
                )

        reefer_containers = [container for container in containers if container.is_reefer]
        for idx, container in enumerate(reefer_containers):
            target = -18.0 if idx % 2 else 2.0
            for reading_idx in range(48):
                recorded = now - timedelta(minutes=(47 - reading_idx) * 30)
                actual = target + 0.4 * math.sin(reading_idx / 3)
                power_on = True
                alarm = "normal"
                if idx == 0 and reading_idx > 38:
                    actual += (reading_idx - 38) * 0.9
                    alarm = "high_temperature"
                if idx == 1 and reading_idx > 43:
                    power_on = False
                    actual += (reading_idx - 43) * 1.2
                    alarm = "power_loss"
                db.add(
                    ReeferReading(
                        organization_id=organization.id,
                        container_id=container.id,
                        recorded_at=recorded,
                        target_c=target,
                        actual_c=round(actual, 2),
                        power_on=power_on,
                        door_open=False,
                        alarm_state=alarm,
                    )
                )

        sample_video = ROOT / "data" / "sample" / "restricted-zone-demo.mp4"
        sample_image = ROOT / "data" / "sample" / "container-code-sample.png"
        generate_sample_video(sample_video)
        generate_container_image(containers[0].number, sample_image)
        camera_positions = [(160, 150), (420, 150), (700, 150), (980, 150), (170, 530), (450, 530), (740, 530), (1050, 500)]
        cameras: list[Camera] = []
        for idx, (x, y) in enumerate(camera_positions):
            camera = Camera(
                organization_id=organization.id,
                terminal_id=terminal.id,
                code=f"CAM-{idx + 1:02d}",
                name=f"Terminal Camera {idx + 1}",
                source=str(sample_video.relative_to(ROOT)) if idx == 0 else "file://sample/offline.mp4",
                status="configured" if idx == 0 else "offline",
                x=x,
                y=y,
            )
            db.add(camera)
            cameras.append(camera)
        db.flush()
        zone = CameraZone(
            organization_id=organization.id,
            camera_id=cameras[0].id,
            name="Crane Restricted Envelope",
            polygon_json=json.dumps([[560, 150], [860, 150], [860, 420], [560, 420]]),
            rule_type="restricted_intrusion",
            severity="high",
            dwell_seconds=0.25,
            cooldown_seconds=30,
        )
        db.add(zone)

        db.add(
            Incident(
                organization_id=organization.id,
                title="Gate queue exceeded shift target",
                incident_type="operational_congestion",
                severity="medium",
                status="investigating",
                assigned_to="Gate Operations",
                created_at=now - timedelta(hours=2),
            )
        )
        db.add(
            WorkOrder(
                organization_id=organization.id,
                equipment_id=equipment[5].id,
                title="Inspect EQ-006 cooling and vibration trend",
                description="Risk indicator increased across the latest telemetry window. Inspect cooling circuit, lubrication and structural fasteners.",
                priority="high",
                status="open",
                due_at=now + timedelta(hours=8),
            )
        )
        for idx in range(24):
            db.add(
                OperationalEvent(
                    organization_id=organization.id,
                    event_id=f"seed-event-{idx:03d}",
                    idempotency_key=f"seed-idem-{idx:03d}",
                    event_type=["container_discharged", "container_placed", "truck_entered", "crane_started"][idx % 4],
                    entity_type=["container", "container", "truck", "equipment"][idx % 4],
                    entity_id=str(idx + 1),
                    occurred_at=now - timedelta(minutes=(23 - idx) * 12),
                    payload_json=json.dumps({"seed": True, "sequence": idx}),
                    source="seed",
                    trace_id=f"seed-trace-{idx:03d}",
                    correlation_id=f"seed-correlation-{idx // 4:03d}",
                    schema_version=1,
                    processing_status="applied",
                    ingested_at=now - timedelta(minutes=(23 - idx) * 12) + timedelta(seconds=1),
                    applied_at=now - timedelta(minutes=(23 - idx) * 12) + timedelta(seconds=1),
                )
            )
        db.add(
            TwinSnapshot(
                organization_id=organization.id,
                captured_at=now - timedelta(hours=6),
                state_json=json.dumps(
                    {
                        "mode": "historical",
                        "terminal": {"id": terminal.id, "name": terminal.name, "code": terminal.code, "geometry": terminal_geometry},
                        "projection": {"containers": {}, "vessels": {}, "trucks": {}, "equipment": {}, "reefers": {}, "incidents": {}},
                    }
                ),
                event_count=0,
            )
        )
        db.add(
            AuditLog(
                organization_id=organization.id,
                user_id=None,
                action="database_seeded",
                entity_type="terminal",
                entity_id=str(terminal.id),
                details_json=json.dumps({"seed": 20260719}),
            )
        )
        db.commit()
        return {
            "organization_id": organization.id,
            "terminal_id": terminal.id,
            "users": len(users),
            "berths": len(berths),
            "vessels": len(vessels),
            "yard_blocks": len(blocks),
            "yard_slots": len(all_slots),
            "containers": len(containers),
            "truck_visits": 120,
            "equipment": len(equipment),
            "telemetry_readings": len(equipment) * 360,
            "reefer_readings": len(reefer_containers) * 48,
            "cameras": len(cameras),
            "sample_video": str(sample_video.relative_to(ROOT)),
            "sample_image": str(sample_image.relative_to(ROOT)),
        }
    finally:
        db.close()


if __name__ == "__main__":
    print(json.dumps(seed_database(reset=True), indent=2))
