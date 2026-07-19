from __future__ import annotations

import json
import sys
from collections import Counter

from harborvision.database import SessionLocal
from harborvision.models import (
    Container,
    ContainerMovement,
    Incident,
    Organization,
    ReeferReading,
    SafetyEvent,
    TruckVisit,
    VesselCall,
    YardSlot,
)
from sqlalchemy import select


def main() -> None:
    checks: dict[str, dict[str, object]] = {}
    failures: list[str] = []
    with SessionLocal() as db:
        organizations = {item.id for item in db.scalars(select(Organization))}
        containers = list(db.scalars(select(Container)))
        slots = {item.id: item for item in db.scalars(select(YardSlot))}
        movements = list(db.scalars(select(ContainerMovement).order_by(ContainerMovement.container_id, ContainerMovement.occurred_at)))
        visits = list(db.scalars(select(TruckVisit)))
        vessels = list(db.scalars(select(VesselCall)))
        reefers = list(db.scalars(select(ReeferReading)))
        incidents = list(db.scalars(select(Incident)))
        safety_event_ids = {item for item in db.scalars(select(SafetyEvent.id))}

        active_slots = [item.slot_id for item in containers if item.slot_id is not None]
        duplicate_slots = [slot_id for slot_id, count in Counter(active_slots).items() if count > 1]
        checks["one_container_per_active_slot"] = {"passed": not duplicate_slots, "duplicates": duplicate_slots[:20]}
        if duplicate_slots:
            failures.append("Multiple containers reference the same active slot")

        active_slot_set = set(active_slots)
        occupancy_mismatch = [slot.id for slot in slots.values() if bool(slot.occupied) != (slot.id in active_slot_set)]
        checks["slot_occupancy_matches_container_location"] = {
            "passed": not occupancy_mismatch,
            "mismatched_slot_ids": occupancy_mismatch[:20],
        }
        if occupancy_mismatch:
            failures.append("YardSlot.occupied disagrees with current container locations")

        bad_vessels = [
            item.id
            for item in vessels
            if item.actual_departure and (not item.actual_arrival or item.actual_departure < item.actual_arrival)
        ]
        checks["vessel_chronology"] = {"passed": not bad_vessels, "vessel_call_ids": bad_vessels}
        if bad_vessels:
            failures.append("Vessel departure precedes arrival")

        bad_visits = [item.id for item in visits if item.exit_at and item.exit_at < item.arrival_at]
        checks["truck_chronology"] = {"passed": not bad_visits, "visit_ids": bad_visits}
        if bad_visits:
            failures.append("Truck exit precedes arrival")

        reefer_container_ids = {item.id for item in containers if item.is_reefer}
        bad_reefer_refs = [item.id for item in reefers if item.container_id not in reefer_container_ids]
        checks["reefer_readings_reference_reefers"] = {"passed": not bad_reefer_refs, "reading_ids": bad_reefer_refs[:20]}
        if bad_reefer_refs:
            failures.append("Reefer telemetry references a non-reefer container")

        bad_incident_refs = [
            item.id for item in incidents if item.source_event_id is not None and item.source_event_id not in safety_event_ids
        ]
        checks["incident_source_references"] = {
            "passed": not bad_incident_refs,
            "incident_ids": bad_incident_refs,
        }
        if bad_incident_refs:
            failures.append("Incident source event does not exist")

        bad_org_refs: list[str] = []
        for label, rows in {
            "container": containers,
            "slot": list(slots.values()),
            "movement": movements,
            "truck_visit": visits,
            "vessel_call": vessels,
            "reefer_reading": reefers,
            "incident": incidents,
        }.items():
            bad_org_refs.extend(f"{label}:{row.id}" for row in rows if row.organization_id not in organizations)
        checks["organization_references"] = {"passed": not bad_org_refs, "records": bad_org_refs[:20]}
        if bad_org_refs:
            failures.append("Organization-scoped rows reference missing organizations")

        by_container: dict[int, list[ContainerMovement]] = {}
        for movement in movements:
            by_container.setdefault(movement.container_id, []).append(movement)
        inconsistent_location = []
        for container in containers:
            history = by_container.get(container.id, [])
            if history and history[-1].to_slot_id != container.slot_id:
                inconsistent_location.append(container.id)
        checks["current_location_matches_latest_movement"] = {
            "passed": not inconsistent_location,
            "container_ids": inconsistent_location[:20],
        }
        if inconsistent_location:
            failures.append("Container current location differs from latest movement")

    result = {"status": "passed" if not failures else "failed", "checks": checks, "failures": failures}
    print(json.dumps(result, indent=2))
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
