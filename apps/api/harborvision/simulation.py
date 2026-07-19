from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .events import ingest_event
from .models import Container, Equipment, EquipmentTelemetry, GateLane, Incident, ReeferReading, TruckVisit, WorkOrder, YardBlock, YardSlot

SCENARIOS = {
    "normal_operations",
    "gate_congestion",
    "yard_capacity_risk",
    "safety_intrusion",
    "equipment_anomaly",
    "reefer_deviation",
}


def run_scenario(db: Session, organization_id: int, scenario: str, speed: float = 10.0) -> dict:
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario}")
    now = datetime.now(UTC)
    created = []
    if scenario == "normal_operations":
        containers = list(db.scalars(select(Container).where(Container.organization_id == organization_id).limit(8)))
        for idx, container in enumerate(containers):
            event = ingest_event(
                db,
                organization_id,
                "container_placed",
                "container",
                str(container.id),
                {"to_slot_id": container.slot_id, "scenario": scenario},
                f"sim-{scenario}-{container.id}-{now:%Y%m%d%H%M%S}",
                now + timedelta(seconds=idx),
                "simulation",
            )
            created.append(event.event_id)
    elif scenario == "gate_congestion":
        lanes = list(db.scalars(select(GateLane).where(GateLane.organization_id == organization_id, GateLane.is_open.is_(True))))
        containers = list(db.scalars(select(Container).where(Container.organization_id == organization_id).limit(18)))
        for idx, container in enumerate(containers):
            arrival = now + timedelta(seconds=idx)
            visit = TruckVisit(
                organization_id=organization_id,
                lane_id=lanes[idx % len(lanes)].id,
                container_id=container.id,
                plate_number=f"SIM-{now:%H%M}-{idx:02d}",
                driver_name=f"Scenario Driver {idx + 1}",
                status="queued",
                appointment_at=arrival - timedelta(minutes=10),
                arrival_at=arrival,
            )
            db.add(visit)
            event = ingest_event(
                db,
                organization_id,
                "truck_entered",
                "truck",
                f"sim-{idx}",
                {"lane_id": visit.lane_id},
                f"sim-gate-{now:%Y%m%d%H%M%S}-{idx}",
                arrival,
                "simulation",
            )
            created.append(event.event_id)
        db.add(
            Incident(
                organization_id=organization_id,
                title="Simulation: gate queue above target",
                incident_type="operational_congestion",
                severity="high",
                status="open",
                assigned_to="Gate Operations",
            )
        )
    elif scenario == "yard_capacity_risk":
        block = db.scalar(
            select(YardBlock).where(YardBlock.organization_id == organization_id, YardBlock.kind == "general").order_by(YardBlock.code)
        )
        if block is None:
            raise RuntimeError("No general yard block is configured")
        free_slots = list(db.scalars(select(YardSlot).where(YardSlot.block_id == block.id, YardSlot.occupied.is_(False)).limit(20)))
        for slot in free_slots:
            slot.occupied = True
        event = ingest_event(
            db,
            organization_id,
            "yard_capacity_threshold",
            "yard_block",
            str(block.id),
            {"block": block.code, "newly_reserved_slots": len(free_slots)},
            f"sim-yard-{now:%Y%m%d%H%M%S}",
            now,
            "simulation",
        )
        created.append(event.event_id)
        db.add(
            Incident(
                organization_id=organization_id,
                title=f"{block.code} approaching safe utilization limit",
                incident_type="yard_capacity",
                severity="high",
                status="open",
                assigned_to="Yard Control",
            )
        )
    elif scenario == "safety_intrusion":
        event = ingest_event(
            db,
            organization_id,
            "safety_intrusion_requested",
            "camera",
            "1",
            {"action": "run sample video processor"},
            f"sim-safety-{now:%Y%m%d%H%M%S}",
            now,
            "simulation",
        )
        created.append(event.event_id)
    elif scenario == "equipment_anomaly":
        equipment = db.scalar(select(Equipment).where(Equipment.organization_id == organization_id).order_by(Equipment.id).offset(5))
        if equipment is None:
            raise RuntimeError("No equipment is configured")
        last = db.scalar(
            select(EquipmentTelemetry)
            .where(EquipmentTelemetry.equipment_id == equipment.id)
            .order_by(EquipmentTelemetry.recorded_at.desc())
        )
        for idx in range(8):
            db.add(
                EquipmentTelemetry(
                    organization_id=organization_id,
                    equipment_id=equipment.id,
                    recorded_at=now + timedelta(minutes=idx * 5),
                    temperature_c=(last.temperature_c if last else 70) + idx * 2.3,
                    vibration_mm_s=(last.vibration_mm_s if last else 4) + idx * 0.45,
                    hydraulic_bar=210 - idx * 1.3,
                    load_pct=78,
                    anomaly_score=2 + idx * 0.4,
                )
            )
        db.add(
            WorkOrder(
                organization_id=organization_id,
                equipment_id=equipment.id,
                title=f"Simulation inspection for {equipment.code}",
                description="Rising temperature and vibration risk indicators require inspection.",
                priority="critical",
                status="open",
                due_at=now + timedelta(hours=4),
            )
        )
        event = ingest_event(
            db,
            organization_id,
            "equipment_fault_precursor",
            "equipment",
            str(equipment.id),
            {"metric": "temperature_vibration", "scenario": scenario},
            f"sim-equipment-{now:%Y%m%d%H%M%S}",
            now,
            "simulation",
        )
        created.append(event.event_id)
    elif scenario == "reefer_deviation":
        container = db.scalar(
            select(Container).where(Container.organization_id == organization_id, Container.is_reefer.is_(True)).order_by(Container.id)
        )
        if container is None:
            raise RuntimeError("No reefer container is configured")
        latest = db.scalar(
            select(ReeferReading).where(ReeferReading.container_id == container.id).order_by(ReeferReading.recorded_at.desc())
        )
        target = latest.target_c if latest else -18
        for idx in range(10):
            db.add(
                ReeferReading(
                    organization_id=organization_id,
                    container_id=container.id,
                    recorded_at=now + timedelta(minutes=idx * 10),
                    target_c=target,
                    actual_c=target + 2 + idx * 0.8,
                    power_on=True,
                    door_open=False,
                    alarm_state="high_temperature",
                )
            )
        db.add(
            Incident(
                organization_id=organization_id,
                title=f"Reefer {container.number} prolonged temperature deviation",
                incident_type="reefer_deviation",
                severity="critical",
                status="open",
                assigned_to="Reefer Operations",
            )
        )
        event = ingest_event(
            db,
            organization_id,
            "reefer_temperature_updated",
            "container",
            str(container.id),
            {"target_c": target, "actual_c": target + 9.2, "alarm": "high_temperature"},
            f"sim-reefer-{now:%Y%m%d%H%M%S}",
            now,
            "simulation",
        )
        created.append(event.event_id)
    db.commit()
    return {
        "scenario": scenario,
        "status": "completed",
        "speed_multiplier": speed,
        "events_created": len(created),
        "event_ids": created,
        "simulation_time": now.isoformat(),
    }
