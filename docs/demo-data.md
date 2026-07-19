# Deterministic Demo Data

NorthStar Container Terminal is fictional. Its geometry, vessel calls, container records, telemetry, images, video, incidents, and users are generated for this repository.

## Default scale

| Entity | Count |
|---|---:|
| Organization | 1 |
| Terminal | 1 |
| Users | 6 |
| Berths | 4 |
| Vessel calls | 6 |
| Yard blocks | 8 |
| Yard slots | 960 |
| Containers | 600 |
| Truck visits | 120 |
| Equipment | 20 |
| Equipment readings | 7,200 |
| Reefer readings | 1,728 |
| Cameras | 8 |

## Consistency guarantees

The seed uses a fixed random seed and the same ORM persistence layer as runtime workflows. It enforces:

- unique active slot per container;
- slot occupancy consistent with current container location;
- valid ISO 6346 container numbers;
- vessel departure after arrival;
- truck exit after arrival;
- reefer readings only for reefer containers;
- organization-consistent references;
- deterministic telemetry trends rather than unrelated random values.

Run `PYTHONPATH=apps/api python scripts/data_integrity.py` after seed or simulation changes.

## Demo label

Generated reports include a demo-data flag. Screenshots and walkthrough assets use fictional `@harborvision.local` accounts and contain no real driver, employee, vessel customer, or port data.
