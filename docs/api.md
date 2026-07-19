# API Guide

Base path: `/api/v1`

Interactive OpenAPI: `/api/v1/docs`

## Authentication

`POST /auth/login` returns a short-lived access token, rotating refresh token, and user summary. Use `Authorization: Bearer <access-token>` for protected calls.

`POST /auth/refresh` rotates a valid refresh token and revokes the old token. Reusing a rotated token is rejected.

`POST /auth/logout` revokes the supplied refresh token.

## Error behavior

- `401`: invalid, expired, or revoked authentication.
- `403`: role or organization permission failure.
- `404`: organization-scoped entity is not visible.
- `409`: state conflict, invalid transition, occupied slot, or conflicting idempotency key.
- `422`: request or business-input validation.
- `429`: login or expensive-operation rate limit.

Responses include `X-Request-ID` and `X-Response-Time-ms`.

## Pagination and filtering

Container and event collections accept search/filter/limit parameters. The local demo uses bounded limits rather than unbounded collection responses. New collection endpoints should preserve the existing shape and organization filtering.

## Selected examples

### Container search

```http
GET /api/v1/containers?q=MSCU&limit=20
Authorization: Bearer <token>
```

### Placement analysis

```http
GET /api/v1/containers/42/placement-analysis?limit=10
Authorization: Bearer <token>
```

The response includes ranked candidates, score factors, rejected candidates/reasons, and current rehandle risk.

### Move a container

```http
POST /api/v1/containers/42/move
Authorization: Bearer <token>
Content-Type: application/json

{"to_slot_id": 355, "idempotency_key": "yard-move-42-355-001"}
```

### Berth assignment

```http
PUT /api/v1/vessels/3/berth-assignment
Authorization: Bearer <token>
Content-Type: application/json

{
  "berth_id": 2,
  "planned_start": "2026-07-20T08:00:00Z",
  "planned_end": "2026-07-21T02:00:00Z"
}
```

A conflict response contains readable reasons such as overlap, insufficient berth length/draft, or maintenance-window conflict.

### Historical playback

```http
GET /api/v1/digital-twin/playback?start=2026-07-19T00:00:00Z&end=2026-07-19T08:00:00Z&limit=500
Authorization: Bearer <token>
```

### Incident transition

```http
POST /api/v1/incidents/7/transition
Authorization: Bearer <token>
Content-Type: application/json

{"status":"investigating"}
```

Dismissal requires `dismissed_reason`. Reopening is audited.

### Incident note

```http
POST /api/v1/incidents/7/notes
Authorization: Bearer <token>
Content-Type: application/json

{"note":"Restricted access signage inspected and temporary barrier installed."}
```

### Simulation run lifecycle

```http
POST /api/v1/simulation/runs
Authorization: Bearer <token>
Content-Type: application/json

{"scenario":"gate_congestion","speed_multiplier":10,"random_seed":20260719}
```

Then call `/simulation/runs/{id}/start`, `/pause`, `/resume`, `/reset`, or `/advance`.

### Reports

```http
GET /api/v1/reports/gate-performance/pdf
GET /api/v1/reports/gate-performance/csv
GET /api/v1/reports/gate-performance/json
Authorization: Bearer <token>
```

Supported names are documented in the web report catalog and `reports.py`.

## Real-time events

`GET /api/v1/events/stream?token=<access-token>` exposes an SSE stream with heartbeat and operational event messages. The browser reconnects automatically and reloads authoritative state after navigation/recovery.
