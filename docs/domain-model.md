# Domain Model

## Organization and terminal

Every operational record carries `organization_id`. A terminal owns local geometry and physical resources. The local release seeds one fictional organization and terminal, while tests create a second organization to verify isolation.

## Vessel calls and berths

A vessel call stores identity, voyage, ETA, planned/actual timestamps, physical length/draft, move target/progress, status, and map position. A berth stores length, draft limit, maintenance window, and geometry. Assignment validation checks time overlap, buffers, physical compatibility, and maintenance.

## Containers, locations, and movement lineage

A container stores an ISO 6346-compatible number, type, size, cargo state, hazard/reefer state, weight, current slot, vessel association, dwell time, expected retrieval, and priority.

`ContainerMovement` is append-only in normal workflows. The current slot is a materialized state that must match the latest accepted movement. The event transaction releases the former slot, reserves the destination, updates the container, and appends movement history atomically.

## Yard structure

A yard block has kind, allocation, closure state, capacity, maximum tier, and geometry. A physical slot has bay, row, tier, occupancy, maximum weight, and optional reservation. The recommendation engine first rejects incompatible slots, then scores valid candidates by distance, stack/rehandle conditions, capacity, retrieval timing, and operational allocation.

## Gate and truck visits

A truck visit records appointment, arrival, processing start/end, exit, lane, driver, vehicle, container, and status. Wait, service, and turnaround are derived from timestamps rather than stored summary values.

## Equipment and telemetry

Equipment records type, state, availability, service time, and location. Time-series rows store load, temperature, vibration, hydraulic pressure, and anomaly values. Phase 2 compares multiple transparent statistical methods and returns the supporting window.

## Reefers

Reefer readings belong only to reefer containers. Each row contains target/actual temperature, power, door, alarm, sensor health, communication health, and time. Assessment considers the latest state and the duration of consecutive deviation.

## Cameras, tracks, rules, and safety events

A camera points to a file or configured stream source. A polygon zone owns rule type, severity, dwell threshold, cooldown, and enabled state. Processing produces confirmed tracks with history and direction. A safety event records camera, zone, frame time, track, confidence, evidence, source, and rule metadata.

## Incidents and work orders

Incidents can originate from safety evidence or operational rules. They carry severity, state, assignment, due time, corrective action, root cause, dismissal reason, and append-only attributed notes.

Work orders carry source, equipment, priority, team, checklist, due date, completion notes, cancellation reason, and lifecycle timestamps. Invalid status changes are rejected.

## Operational events and snapshots

Events preserve source time, ingestion time, applied time, schema version, idempotency, trace/correlation/causation, payload, and processing status. Snapshots accelerate replay. See [event-model.md](event-model.md).
