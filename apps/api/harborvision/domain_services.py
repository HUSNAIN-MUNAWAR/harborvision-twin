from __future__ import annotations

from datetime import UTC, datetime
from statistics import mean
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .algorithms import berth_conflicts, rolling_z_scores
from .models import (
    Berth,
    Container,
    EquipmentTelemetry,
    ReeferReading,
    TruckVisit,
    VesselCall,
    YardBlock,
    YardSlot,
)

WORK_ORDER_TRANSITIONS: dict[str, set[str]] = {
    "open": {"planned", "cancelled"},
    "planned": {"in_progress", "cancelled"},
    "in_progress": {"blocked", "completed", "cancelled"},
    "blocked": {"in_progress", "cancelled"},
    "completed": {"verified", "in_progress"},
    "verified": set(),
    "cancelled": {"open"},
}


def can_transition_work_order(current: str, target: str) -> bool:
    return target in WORK_ORDER_TRANSITIONS.get(current, set())


def validate_berth_assignment(
    db: Session,
    organization_id: int,
    vessel: VesselCall,
    berth: Berth,
    planned_start: datetime,
    planned_end: datetime,
) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    if planned_end <= planned_start:
        conflicts.append({"code": "invalid_window", "message": "Planned end must be after planned start."})
    if vessel.vessel_length_m > berth.length_m:
        conflicts.append(
            {
                "code": "length_exceeded",
                "message": f"Vessel length {vessel.vessel_length_m:.1f} m exceeds berth length {berth.length_m:.1f} m.",
            }
        )
    if vessel.draft_m > berth.draft_limit_m:
        conflicts.append(
            {
                "code": "draft_exceeded",
                "message": f"Vessel draft {vessel.draft_m:.1f} m exceeds berth limit {berth.draft_limit_m:.1f} m.",
            }
        )
    if (
        berth.maintenance_start
        and berth.maintenance_end
        and planned_start < berth.maintenance_end
        and planned_end > berth.maintenance_start
    ):
        conflicts.append(
            {
                "code": "maintenance_window",
                "message": "The requested assignment overlaps a berth maintenance window.",
                "maintenance_start": berth.maintenance_start.isoformat(),
                "maintenance_end": berth.maintenance_end.isoformat(),
            }
        )
    for item in berth_conflicts(db, organization_id, berth.id, planned_start, planned_end, exclude_id=vessel.id):
        conflicts.append(
            {
                "code": "schedule_overlap",
                "message": f"Overlaps vessel call {item.vessel_name} ({item.voyage_number}).",
                "vessel_call_id": item.id,
                "planned_start": item.planned_start.isoformat() if item.planned_start else None,
                "planned_end": item.planned_end.isoformat() if item.planned_end else None,
            }
        )
    return conflicts


def validate_yard_placement(container: Container, slot: YardSlot, block: YardBlock, now: datetime | None = None) -> list[str]:
    now = now or datetime.now(UTC)
    reasons: list[str] = []
    if block.is_closed:
        reasons.append("block is operationally closed")
    if slot.occupied and slot.id != container.slot_id:
        reasons.append("slot is occupied")
    if slot.reserved_until:
        reserved = slot.reserved_until if slot.reserved_until.tzinfo else slot.reserved_until.replace(tzinfo=UTC)
        if reserved > now:
            reasons.append(f"slot is reserved until {reserved.isoformat()}")
    if slot.tier > block.max_tier:
        reasons.append("slot tier exceeds block stack limit")
    if container.weight_kg > slot.max_weight_kg:
        reasons.append("container weight exceeds slot rating")
    if container.is_reefer and block.kind != "reefer":
        reasons.append("reefer container requires a powered reefer block")
    if container.is_hazardous and block.kind != "hazardous":
        reasons.append("hazardous container requires the segregated hazardous block")
    if not container.is_reefer and not container.is_hazardous and block.kind in {"reefer", "hazardous"}:
        reasons.append(f"general cargo cannot consume {block.kind}-only capacity")
    if block.allocation not in {"mixed", container.movement_type}:
        reasons.append(f"block is allocated to {block.allocation} cargo")
    return reasons


def rehandle_risk(db: Session, organization_id: int, container: Container) -> dict[str, Any]:
    if not container.slot_id:
        return {"score": 0, "level": "none", "blocking_containers": [], "method": "container is not in a stack"}
    slot = db.get(YardSlot, container.slot_id)
    if not slot:
        return {"score": 0, "level": "unknown", "blocking_containers": [], "method": "current slot is unavailable"}
    above_slots = list(
        db.scalars(
            select(YardSlot).where(
                YardSlot.organization_id == organization_id,
                YardSlot.block_id == slot.block_id,
                YardSlot.bay == slot.bay,
                YardSlot.row == slot.row,
                YardSlot.tier > slot.tier,
                YardSlot.occupied.is_(True),
            )
        )
    )
    blockers = list(
        db.scalars(
            select(Container).where(
                Container.organization_id == organization_id,
                Container.slot_id.in_([item.id for item in above_slots]) if above_slots else Container.id == -1,
            )
        )
    )
    priority_pressure = sum(max(0, container.retrieval_priority - item.retrieval_priority) for item in blockers)
    score = min(100, len(blockers) * 25 + priority_pressure * 0.5)
    level = "high" if score >= 60 else "medium" if score >= 30 else "low"
    return {
        "score": round(score, 1),
        "level": level,
        "blocking_containers": [{"id": item.id, "number": item.number, "retrieval_priority": item.retrieval_priority} for item in blockers],
        "expected_rehandles": len(blockers),
        "method": "tier blockers plus retrieval-priority pressure heuristic",
    }


def gate_visit_timeline(visit: TruckVisit) -> list[dict[str, Any]]:
    stages = [
        ("appointment", visit.appointment_at),
        ("arrival", visit.arrival_at),
        ("processing_started", visit.processing_start),
        ("processing_completed", visit.processing_end),
        ("exit", visit.exit_at),
    ]
    return [{"stage": name, "time": value.isoformat() if value else None, "complete": value is not None} for name, value in stages]


def assess_reefer(readings: list[ReeferReading], tolerance_c: float = 2.0) -> dict[str, Any]:
    if not readings:
        return {"state": "missing_telemetry", "severity": "high", "duration_minutes": 0, "explanation": "No reefer telemetry is available."}
    ordered = sorted(readings, key=lambda item: item.recorded_at)
    latest = ordered[-1]
    deviation = latest.actual_c - latest.target_c
    if latest.communication_ok is False:
        state, severity, action = "missing_telemetry", "high", "Inspect sensor communications and power feed."
    elif latest.sensor_ok is False:
        state, severity, action = "sensor_fault", "high", "Validate the sensor and compare against a calibrated probe."
    elif not latest.power_on:
        state, severity, action = "power_loss", "critical", "Restore reefer power and verify plug integrity immediately."
    elif latest.door_open:
        state, severity, action = "door_open", "high", "Confirm door closure and inspect the seal."
    elif deviation > tolerance_c:
        state, severity, action = (
            "high_temperature",
            "critical" if deviation > tolerance_c * 2 else "high",
            "Inspect refrigeration unit and cargo set point.",
        )
    elif deviation < -tolerance_c:
        state, severity, action = "low_temperature", "high", "Validate set point and refrigeration controller."
    else:
        state, severity, action = "normal", "normal", "Continue monitoring."

    duration_minutes = 0.0
    if state != "normal":
        start = latest.recorded_at
        for item in reversed(ordered):
            item_deviation = item.actual_c - item.target_c
            same = (
                (state == "power_loss" and not item.power_on)
                or (state == "door_open" and item.door_open)
                or (state == "sensor_fault" and item.sensor_ok is False)
                or (state == "missing_telemetry" and item.communication_ok is False)
                or (state == "high_temperature" and item_deviation > tolerance_c)
                or (state == "low_temperature" and item_deviation < -tolerance_c)
            )
            if not same:
                break
            start = item.recorded_at
        duration_minutes = max(0.0, (latest.recorded_at - start).total_seconds() / 60)
    return {
        "state": state,
        "severity": severity,
        "target_c": latest.target_c,
        "actual_c": latest.actual_c,
        "deviation_c": round(deviation, 2),
        "tolerance_c": tolerance_c,
        "duration_minutes": round(duration_minutes, 1),
        "last_reading": latest.recorded_at.isoformat(),
        "suggested_action": action,
        "explanation": f"Current temperature is {deviation:+.2f}°C from target; condition persisted for {duration_minutes:.1f} minutes.",
    }


def equipment_risk_methods(telemetry: list[EquipmentTelemetry]) -> dict[str, Any]:
    if not telemetry:
        return {"severity": "normal", "score": 0, "methods": {}, "explanations": ["No telemetry is available."]}
    rows = sorted(telemetry, key=lambda item: item.recorded_at)
    temps = [row.temperature_c for row in rows]
    vibrations = [row.vibration_mm_s for row in rows]
    temp_z = rolling_z_scores(temps)[-1]
    vibration_z = rolling_z_scores(vibrations)[-1]
    alpha = 0.25
    ewma = temps[0]
    for value in temps[1:]:
        ewma = alpha * value + (1 - alpha) * ewma
    rate = (temps[-1] - temps[-6]) / 5 if len(temps) >= 6 else 0.0
    baseline = mean(temps[max(0, len(temps) - 24) : -1] or temps)
    score = max(abs(temp_z), abs(vibration_z), max(0.0, rate / 0.8), max(0.0, (temps[-1] - ewma) / 2.0))
    severity = "critical" if score >= 4 else "high" if score >= 3 else "watch" if score >= 2 else "normal"
    explanations = [
        f"Motor temperature is {temps[-1]:.1f}°C versus a recent baseline of {baseline:.1f}°C.",
        f"Temperature rate of change is {rate:+.2f}°C per reading across the latest six readings.",
        f"Vibration rolling deviation is {vibration_z:+.2f}σ.",
    ]
    return {
        "score": round(score, 3),
        "severity": severity,
        "methods": {
            "rolling_z_score": {"temperature": round(temp_z, 3), "vibration": round(vibration_z, 3)},
            "ewma": {"alpha": alpha, "temperature_c": round(ewma, 2)},
            "rate_of_change": {"temperature_c_per_reading": round(rate, 3)},
        },
        "explanations": explanations,
        "suggested_action": "Inspect cooling, lubrication and structural fasteners." if severity != "normal" else "Continue monitoring.",
    }


def yard_slot_analysis(db: Session, organization_id: int, container: Container, limit: int = 5) -> dict[str, Any]:
    from .algorithms import recommend_yard_slot

    accepted = [item.__dict__ for item in recommend_yard_slot(db, organization_id, container, limit=limit)]
    rejected: list[dict[str, Any]] = []
    rows = db.execute(
        select(YardSlot, YardBlock)
        .join(YardBlock, YardSlot.block_id == YardBlock.id)
        .where(YardSlot.organization_id == organization_id, YardBlock.organization_id == organization_id)
        .order_by(YardBlock.code, YardSlot.bay, YardSlot.row, YardSlot.tier)
    ).all()
    valid_count = 0
    for slot, block in rows:
        reasons = validate_yard_placement(container, slot, block)
        if reasons:
            if len(rejected) < 25:
                rejected.append(
                    {
                        "slot_id": slot.id,
                        "block_code": block.code,
                        "bay": slot.bay,
                        "row": slot.row,
                        "tier": slot.tier,
                        "reasons": reasons,
                    }
                )
        else:
            valid_count += 1
    return {
        "container_id": container.id,
        "container_number": container.number,
        "recommendations": accepted,
        "rejected_candidates": rejected,
        "candidate_summary": {"total_slots": len(rows), "valid_slots": valid_count, "rejected_slots": len(rows) - valid_count},
        "rehandle_risk": rehandle_risk(db, organization_id, container),
        "method": "deterministic compatibility filters plus weighted travel, utilization, tier and rehandle heuristic",
    }
