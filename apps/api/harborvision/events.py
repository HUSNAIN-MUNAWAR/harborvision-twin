from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Container, ContainerMovement, OperationalEvent, Terminal, TwinSnapshot, YardSlot


class DuplicateEvent(Exception):
    pass


class IdempotencyConflict(Exception):
    pass


STATE_MUTATING_EVENTS = {
    "container_placed",
    "container_yard_move",
    "container_relocated",
    "container_gate_out",
    "vessel_arrived",
    "vessel_berthed",
    "vessel_operation_started",
    "vessel_operation_completed",
    "vessel_departed",
    "reefer_temperature_updated",
}


def ingest_event(
    db: Session,
    organization_id: int,
    event_type: str,
    entity_type: str,
    entity_id: str,
    payload: dict[str, Any],
    idempotency_key: str,
    occurred_at: datetime | None = None,
    source: str = "api",
    trace_id: str | None = None,
    correlation_id: str | None = None,
    causation_id: str | None = None,
    schema_version: int = 1,
    terminal_id: int | None = None,
) -> OperationalEvent:
    existing = db.scalar(select(OperationalEvent).where(OperationalEvent.idempotency_key == idempotency_key))
    canonical_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if existing:
        existing_payload = json.dumps(json.loads(existing.payload_json or "{}"), sort_keys=True, separators=(",", ":"))
        if (
            existing.organization_id != organization_id
            or existing.event_type != event_type
            or existing.entity_type != entity_type
            or existing.entity_id != str(entity_id)
            or existing_payload != canonical_payload
        ):
            raise IdempotencyConflict("Idempotency key was already used for a different event")
        return existing

    event_time = occurred_at or datetime.now(UTC)
    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=UTC)
    terminal_id = terminal_id or db.scalar(select(Terminal.id).where(Terminal.organization_id == organization_id))
    correlation = correlation_id or trace_id or str(uuid.uuid4())
    event = OperationalEvent(
        organization_id=organization_id,
        terminal_id=terminal_id,
        event_id=str(uuid.uuid4()),
        idempotency_key=idempotency_key,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=str(entity_id),
        payload_json=canonical_payload,
        occurred_at=event_time,
        ingested_at=datetime.now(UTC),
        source=source,
        trace_id=trace_id or correlation,
        correlation_id=correlation,
        causation_id=causation_id,
        schema_version=schema_version,
        processing_status="pending",
    )
    db.add(event)
    db.flush()

    latest = db.scalar(
        select(OperationalEvent)
        .where(
            OperationalEvent.organization_id == organization_id,
            OperationalEvent.entity_type == entity_type,
            OperationalEvent.entity_id == str(entity_id),
            OperationalEvent.id != event.id,
            OperationalEvent.processing_status == "applied",
        )
        .order_by(OperationalEvent.occurred_at.desc(), OperationalEvent.id.desc())
    )
    latest_time = latest.occurred_at if latest else None
    if latest_time and latest_time.tzinfo is None:
        latest_time = latest_time.replace(tzinfo=UTC)
    if event_type in STATE_MUTATING_EVENTS and latest_time and event_time < latest_time:
        event.processing_status = "stale_ignored"
        return event

    try:
        apply_event(db, event)
        event.processing_status = "applied"
        event.applied_at = datetime.now(UTC)
    except Exception:
        event.processing_status = "failed"
        raise
    return event


def apply_event(db: Session, event: OperationalEvent) -> None:
    payload = json.loads(event.payload_json or "{}")
    if event.entity_type != "container":
        return
    container = db.get(Container, int(event.entity_id))
    if not container or container.organization_id != event.organization_id:
        return
    if event.event_type in {"container_placed", "container_yard_move", "container_relocated"}:
        to_slot_id = payload.get("to_slot_id")
        to_slot = db.get(YardSlot, to_slot_id) if to_slot_id else None
        if to_slot and to_slot.organization_id != event.organization_id:
            raise ValueError("Target slot belongs to a different organization")
        from_slot = container.slot_id
        if from_slot and from_slot != to_slot_id:
            previous = db.get(YardSlot, from_slot)
            if previous:
                previous.occupied = False
        if to_slot:
            if to_slot.occupied and to_slot.id != from_slot:
                raise ValueError("Target slot is occupied")
            to_slot.occupied = True
        container.slot_id = to_slot_id
        container.last_movement_at = event.occurred_at
        existing_movement = db.scalar(select(ContainerMovement).where(ContainerMovement.source_event_id == event.event_id))
        if not existing_movement:
            db.add(
                ContainerMovement(
                    organization_id=event.organization_id,
                    container_id=container.id,
                    from_slot_id=from_slot,
                    to_slot_id=container.slot_id,
                    movement_type=event.event_type,
                    occurred_at=event.occurred_at,
                    source_event_id=event.event_id,
                )
            )
    elif event.event_type == "container_gate_out":
        if container.slot_id:
            current = db.get(YardSlot, container.slot_id)
            if current:
                current.occupied = False
        container.status = "departed"
        container.slot_id = None
        container.last_movement_at = event.occurred_at


def snapshot(db: Session, organization_id: int, state: dict[str, Any], captured_at: datetime | None = None) -> TwinSnapshot:
    count = db.query(OperationalEvent).filter(OperationalEvent.organization_id == organization_id).count()
    item = TwinSnapshot(
        organization_id=organization_id,
        captured_at=captured_at or datetime.now(UTC),
        state_json=json.dumps(state),
        event_count=count,
    )
    db.add(item)
    return item
