from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    Berth,
    Camera,
    Container,
    Equipment,
    GateLane,
    Incident,
    OperationalEvent,
    ReeferReading,
    Terminal,
    TruckVisit,
    TwinSnapshot,
    VesselCall,
    WorkOrder,
    YardBlock,
    YardSlot,
)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def build_live_state(db: Session, organization_id: int) -> dict[str, Any]:
    terminal = db.scalar(select(Terminal).where(Terminal.organization_id == organization_id))
    if terminal is None:
        raise LookupError("Terminal not found")
    berths = list(db.scalars(select(Berth).where(Berth.organization_id == organization_id).order_by(Berth.code)))
    vessels = list(db.scalars(select(VesselCall).where(VesselCall.organization_id == organization_id).order_by(VesselCall.eta)))
    blocks = list(db.scalars(select(YardBlock).where(YardBlock.organization_id == organization_id).order_by(YardBlock.code)))
    equipment = list(db.scalars(select(Equipment).where(Equipment.organization_id == organization_id)))
    cameras = list(db.scalars(select(Camera).where(Camera.organization_id == organization_id)))
    incidents = list(
        db.scalars(select(Incident).where(Incident.organization_id == organization_id, Incident.status.not_in(["resolved", "dismissed"])))
    )
    work_orders = list(
        db.scalars(
            select(WorkOrder).where(WorkOrder.organization_id == organization_id, WorkOrder.status.not_in(["verified", "cancelled"]))
        )
    )
    lanes = list(db.scalars(select(GateLane).where(GateLane.organization_id == organization_id)))
    queued = list(
        db.scalars(select(TruckVisit).where(TruckVisit.organization_id == organization_id, TruckVisit.status.in_(["queued", "processing"])))
    )
    block_items: list[dict[str, Any]] = []
    for block in blocks:
        occupied = (
            db.scalar(select(func.count()).select_from(YardSlot).where(YardSlot.block_id == block.id, YardSlot.occupied.is_(True))) or 0
        )
        total = db.scalar(select(func.count()).select_from(YardSlot).where(YardSlot.block_id == block.id)) or 0
        block_items.append(
            {
                "id": block.id,
                "code": block.code,
                "kind": block.kind,
                "is_closed": block.is_closed,
                "allocation": block.allocation,
                "x": block.x,
                "y": block.y,
                "width": block.width,
                "height": block.height,
                "occupied": occupied,
                "capacity": total,
                "utilization": round(occupied / total, 3) if total else 0,
            }
        )
    reefer_alarms: list[dict[str, Any]] = []
    reefers = list(db.scalars(select(Container).where(Container.organization_id == organization_id, Container.is_reefer.is_(True))))
    for container in reefers:
        reading = db.scalar(
            select(ReeferReading).where(ReeferReading.container_id == container.id).order_by(ReeferReading.recorded_at.desc())
        )
        if reading and reading.alarm_state != "normal":
            reefer_alarms.append(
                {
                    "container_id": container.id,
                    "number": container.number,
                    "state": reading.alarm_state,
                    "actual_c": reading.actual_c,
                    "target_c": reading.target_c,
                    "slot_id": container.slot_id,
                }
            )
    return {
        "terminal": {"id": terminal.id, "name": terminal.name, "code": terminal.code, "geometry": json.loads(terminal.geometry_json)},
        "berths": [
            {
                "id": item.id,
                "code": item.code,
                "name": item.name,
                "length_m": item.length_m,
                "draft_limit_m": item.draft_limit_m,
                "x": item.x,
                "y": item.y,
                "width": item.width,
                "height": item.height,
            }
            for item in berths
        ],
        "vessels": [
            {
                "id": item.id,
                "name": item.vessel_name,
                "status": item.status,
                "berth_id": item.berth_id,
                "x": item.x,
                "y": item.y,
                "moves": item.actual_moves,
                "target_moves": item.target_moves,
                "estimated_completion": _estimate_completion(item),
            }
            for item in vessels
        ],
        "yard_blocks": block_items,
        "equipment": [
            {
                "id": item.id,
                "code": item.code,
                "type": item.equipment_type,
                "state": item.state,
                "availability": item.availability,
                "x": item.x,
                "y": item.y,
            }
            for item in equipment
        ],
        "cameras": [
            {"id": item.id, "code": item.code, "status": item.status, "fps": item.fps, "x": item.x, "y": item.y} for item in cameras
        ],
        "gate_lanes": [
            {
                "id": item.id,
                "code": item.code,
                "direction": item.direction,
                "is_open": item.is_open,
                "x": item.x,
                "y": item.y,
                "queue_length": sum(1 for visit in queued if visit.lane_id == item.id),
            }
            for item in lanes
        ],
        "incidents": [{"id": item.id, "title": item.title, "severity": item.severity, "status": item.status} for item in incidents],
        "work_orders": [
            {"id": item.id, "title": item.title, "priority": item.priority, "status": item.status, "equipment_id": item.equipment_id}
            for item in work_orders
        ],
        "reefer_alarms": reefer_alarms,
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "live",
    }


def _estimate_completion(vessel: VesselCall) -> str | None:
    if vessel.actual_moves <= 0 or vessel.target_moves <= vessel.actual_moves:
        return _iso(vessel.operation_completed or vessel.planned_end)
    start = vessel.operation_start or vessel.actual_arrival or vessel.planned_start
    if not start:
        return _iso(vessel.planned_end)
    now = datetime.now(UTC)
    normalized_start = start if start.tzinfo else start.replace(tzinfo=UTC)
    elapsed_hours = max((now - normalized_start).total_seconds() / 3600, 0.1)
    rate = vessel.actual_moves / elapsed_hours
    if rate <= 0:
        return _iso(vessel.planned_end)
    from datetime import timedelta

    return (now + timedelta(hours=(vessel.target_moves - vessel.actual_moves) / rate)).isoformat()


def serialize_event(event: OperationalEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "event_id": event.event_id,
        "event_type": event.event_type,
        "entity_type": event.entity_type,
        "entity_id": event.entity_id,
        "occurred_at": event.occurred_at.isoformat(),
        "ingested_at": event.ingested_at.isoformat() if event.ingested_at else None,
        "source": event.source,
        "schema_version": event.schema_version,
        "processing_status": event.processing_status,
        "correlation_id": event.correlation_id,
        "causation_id": event.causation_id,
        "payload": json.loads(event.payload_json or "{}"),
    }


def playback_window(
    db: Session,
    organization_id: int,
    start: datetime,
    end: datetime,
    limit: int = 500,
) -> dict[str, Any]:
    if end <= start:
        raise ValueError("Playback end must be after start")
    snapshot = db.scalar(
        select(TwinSnapshot)
        .where(TwinSnapshot.organization_id == organization_id, TwinSnapshot.captured_at <= start)
        .order_by(TwinSnapshot.captured_at.desc())
    )
    events = list(
        db.scalars(
            select(OperationalEvent)
            .where(
                OperationalEvent.organization_id == organization_id,
                OperationalEvent.occurred_at >= start,
                OperationalEvent.occurred_at <= end,
            )
            .order_by(OperationalEvent.occurred_at, OperationalEvent.id)
            .limit(limit)
        )
    )
    projection: dict[str, Any] = (
        json.loads(snapshot.state_json)
        if snapshot
        else {
            "mode": "historical",
            "projection": {"containers": {}, "vessels": {}, "trucks": {}, "equipment": {}, "reefers": {}, "incidents": {}},
        }
    )
    projection["mode"] = "historical"
    projection["playback_at"] = start.isoformat()
    frames: list[dict[str, Any]] = []
    for event in events:
        delta = _project_event(projection, event)
        frames.append({"at": event.occurred_at.isoformat(), "event": serialize_event(event), "delta": delta})
    projection["playback_at"] = end.isoformat()
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "snapshot": {"id": snapshot.id, "captured_at": snapshot.captured_at.isoformat()} if snapshot else None,
        "event_count": len(frames),
        "truncated": len(frames) >= limit,
        "frames": frames,
        "state_at_end": projection,
        "reconstruction": "nearest persisted snapshot plus ordered operational events",
    }


def _project_event(state: dict[str, Any], event: OperationalEvent) -> dict[str, Any]:
    projection = state.setdefault(
        "projection", {"containers": {}, "vessels": {}, "trucks": {}, "equipment": {}, "reefers": {}, "incidents": {}}
    )
    bucket_name = {
        "container": "containers",
        "vessel": "vessels",
        "truck": "trucks",
        "equipment": "equipment",
        "incident": "incidents",
    }.get(event.entity_type, f"{event.entity_type}s")
    bucket = projection.setdefault(bucket_name, {})
    payload = json.loads(event.payload_json or "{}")
    current = bucket.setdefault(event.entity_id, {})
    current.update(payload)
    current["last_event"] = event.event_type
    current["updated_at"] = event.occurred_at.isoformat()
    return {"bucket": bucket_name, "entity_id": event.entity_id, "state": dict(current)}
