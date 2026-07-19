# Digital Twin

## Purpose

The digital twin is the shared operational view of NorthStar Container Terminal. It is not a separate frontend simulation. Live state is assembled from organization-scoped relational records, while historical state is reconstructed from persisted snapshots and normalized operational events.

## Coordinate system

The demo terminal uses a documented local Cartesian grid stored in `Terminal.geometry_json`:

- origin: southwest corner of the fictional terminal;
- units: local metres represented in a normalized display grid;
- extent: defined by the seeded terminal geometry;
- layers: berths, vessels, yard blocks, equipment, cameras, gates, incidents, work orders, and reefer alarms.

No proprietary port map is used. A production adapter can transform this local geometry into site GIS and PostGIS geometries.

## Live state

`GET /api/v1/digital-twin/state` calls the central state service. It derives:

- current vessel calls and berth occupancy;
- planned and actual move progress;
- physical yard occupancy from active container slots;
- gate-lane queue counts from truck stages;
- equipment position/state/availability;
- camera status and measured processing rate;
- unresolved incidents and unverified work orders;
- latest reefer alarms.

The response is organization-scoped. The UI does not maintain an unrelated authoritative copy.

## Historical playback

`GET /api/v1/digital-twin/playback` accepts an ISO-8601 start and end time. Reconstruction follows this sequence:

1. Find the newest snapshot at or before the requested start.
2. Load organization-scoped operational events in `(occurred_at, id)` order.
3. Apply each event to a pure historical projection.
4. Return ordered frames containing event provenance and the state delta.
5. Return the reconstructed projection at the end of the window.

The browser provides start/end selection, a timeline slider, play, pause, speed controls, and event inspection. Returning to live mode reloads current relational state.

## Event ordering and stale data

State-changing events are compared with the latest applied event for the same entity. An older event is retained with processing status `stale_ignored`; it remains auditable but does not roll current state backward.

## Layer preferences

The web console persists visibility choices in browser local storage. Layer settings affect actual SVG rendering rather than only changing checkbox appearance.

## Scale boundary

The current replay endpoint is designed for local engineering evaluation and caps frames per request. A high-volume deployment should use partitioned event storage, periodic snapshots, streaming materialized projections, geospatial indexes, and server-side pagination.
