# Phase 2 Engineering Audit

Audit date: **2026-07-19**

This audit compares the Phase 1 repository with the Phase 2 release requirements. It records the state observed before hardening and the release action taken. “Verified” means a command or automated test exercises the behavior; it does not mean commercial certification.

## Classification summary

| Area | Initial classification | Phase 2 disposition |
|---|---|---|
| Login, password hashing, access tokens | Fully implemented | Preserved; refresh rotation, logout revocation, disabled-user and rate-limit behavior verified |
| Organization isolation | Implemented and tested on primary reads | Expanded to state changes, incidents, work orders, events, reports, and replay queries |
| Refresh-token lifecycle | Implemented but logout was disconnected | Added explicit revocation endpoint and browser logout integration |
| Role authorization | Partially implemented | Permission checks retained and expanded for incident/work-order mutation and audit access |
| Database migrations | Clean install only | Added defensive Phase 1 → Phase 2 migration and tested both clean and in-place upgrade paths |
| Digital-twin current state | Fully implemented | Centralized in one state service with vessel, berth, yard, gate, equipment, camera, incident, work-order, and reefer state |
| Historical playback | Misleadingly documented / partial | Added nearest-snapshot reconstruction, ordered events, time-window API, and browser play/pause/speed/event controls |
| Operational event provenance | Partially implemented | Added schema version, ingestion/applied time, terminal, correlation, causation, and processing status |
| Duplicate event handling | Implemented | Hardened to reject idempotency-key reuse with conflicting content |
| Out-of-order event handling | Missing | Stale state-mutating events persist as `stale_ignored` and do not corrupt current state |
| Berth conflict checks | Time overlap only | Added vessel length, draft, maintenance-window, buffer, and readable conflict reasons |
| Yard slot recommendation | Fully implemented heuristic | Added closure, allocation, reservation, weight, retrieval timing, candidate rejection, and rehandle-risk explanation |
| Container movement | Persisted but route owned slot mutations | Moved state change into the event engine transaction and retained append-only movement lineage |
| Gate metrics | Fully implemented summary | Added per-visit stage timeline and calculated wait/service/turnaround metrics |
| OCR | Working CPU baseline | Added stored crop/enhanced evidence, adapter metadata, reviewer attribution, and deterministic evaluation command |
| Video intrusion pipeline | Working CPU baseline | Added confirmed tracks, history, direction, missed-frame handling, and richer evidence-chain metadata |
| Equipment anomaly indicators | One rolling method | Added rolling z-score, EWMA, rate-of-change comparison, supporting windows, and data-derived explanations |
| Reefer alerts | Latest-value alarm only | Added sensor/communication state, duration, severity, trigger explanation, and suggested action |
| Incident lifecycle | Status transitions only | Added dismissal reason, reopening count, assignment/due fields, attributed append-only notes, and detail view |
| Work orders | Read-only | Added enforced lifecycle, team assignment, checklist/evidence fields, completion/verification timestamps, and audits |
| Reports | Three exports | Expanded to ten report families in PDF, CSV, and JSON with generation metadata and demo-data labels |
| Simulation | Deterministic batch calls | Added persisted simulation runs with create/start/pause/resume/reset/advance state machine |
| Readiness | Database-only | Added storage probe, Redis status, worker-heartbeat age, environment label, and dependency detail |
| Data-integrity validation | Missing standalone gate | Added executable checks for slot uniqueness, occupancy, chronology, tenancy, references, and movement lineage |
| Frontend operations | Strong but several decorative controls | Connected map layers, playback, incidents, work orders, reports, logout, and system-health views |
| Open-source governance | Partial | Added MIT license, code of conduct, issue forms, pull-request template, disclosure policy, changelog, and contributor guide |
| GitHub publication | Missing | Prepared locally; remote publication depends on an authenticated repository-creation/push channel |

## Release backlog completed

1. Protect current state from stale operational events.
2. Implement real historical replay from snapshots and events.
3. Move container placement into one transactional event path.
4. Expand berth and yard compatibility validation.
5. Mature incident and work-order lifecycles.
6. Add reefer duration/explanation and multi-method equipment anomaly analysis.
7. Expand report families and persisted simulation controls.
8. Add Phase 2 migration and data-integrity gates.
9. Connect the browser console to Phase 2 APIs.
10. Add open-source governance, CI, release documentation, and repository hygiene checks.

## Remaining honest limitations

- The browser client is a zero-build ES-module application rather than Next.js.
- PostGIS, Redis, MinIO, and Docker are configured, but runtime validation requires Docker on the host.
- The local worker is a heartbeat/separable-process baseline, not a production distributed job queue with a dead-letter service.
- The verified video baseline is motion tracking and polygon rules; semantic person, vehicle, PPE, and proximity adapters are not claimed as enabled.
- Synthetic OCR evaluation does not establish field accuracy.
- No TOS, PLC, SCADA, RTSP, identity-provider, or production GIS integration is included.
