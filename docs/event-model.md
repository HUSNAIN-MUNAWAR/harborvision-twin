# Operational Event Model

Operational events provide provenance and replay without replacing the relational operational model.

## Canonical fields

| Field | Purpose |
|---|---|
| `event_id` | Stable unique identifier |
| `organization_id` | Tenant boundary |
| `terminal_id` | Optional terminal scope |
| `event_type` | Versioned business event name |
| `entity_type`, `entity_id` | Projection target |
| `occurred_at` | Source/business time |
| `ingested_at` | Platform receipt time |
| `applied_at` | Successful state-application time |
| `source` | API, simulation, vision, OCR, or adapter |
| `schema_version` | Payload contract version |
| `correlation_id` | End-to-end workflow grouping |
| `causation_id` | Direct preceding event when known |
| `idempotency_key` | Duplicate request protection |
| `processing_status` | `pending`, `applied`, `stale_ignored`, or failure state |
| `payload_json` | Event-specific validated data |

## Idempotency

Reusing an idempotency key with the same canonical event returns the existing record. Reusing it with different event content raises a conflict. This prevents accidental “success” for a semantically different request.

## Application transaction

For container placement, event creation, slot release/reservation, container location update, and append-only movement history occur in one database transaction. An occupied or cross-organization destination aborts the workflow.

## Out-of-order handling

An event older than the latest applied state-changing event for the same entity is persisted with `stale_ignored`. It can be inspected and replayed historically, but it cannot overwrite live state.

## Snapshots

A snapshot stores an organization-scoped projection, capture time, and source event count. Snapshots are acceleration points, not the only source of truth.

## Schema evolution

Payload changes must increment `schema_version`. Consumers should ignore unknown fields and reject unsupported required semantics. Production integrations should publish schemas through a registry and retain compatibility tests.
