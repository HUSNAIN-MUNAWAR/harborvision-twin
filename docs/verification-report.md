# HarborVision Twin Launch Verification Report

Verification date: **2026-07-19**. Application timestamps are stored in UTC.

## Release scope

This launch verification covers the public open-source repository preparation pass plus the NGA World Port Index public-dataset integration: documentation accuracy, local FastAPI startup, deterministic demo seed data, WPI sample preparation, migrations, API smoke tests, backend tests, static analysis, frontend syntax, dependency consistency, screenshot refresh, and repository hygiene.

## Verification environment

| Component | Verified value |
|---|---|
| Host | Windows / PowerShell |
| Python | 3.12.10 through the Python launcher |
| Node.js | 24.18.0 |
| GitHub CLI | 2.95.0, authenticated as `HUSNAIN-MUNAWAR` |
| Local database | SQLite through SQLAlchemy 2 and Alembic |
| Docker | Not installed on this host |
| Tesseract OCR | Not installed on PATH; Winget installer was canceled by Windows |
| Playwright/Chromium | Playwright 1.61.0 with managed Chromium 149 installed |

## Quality gates

| Category | Command | Result | Summary |
|---|---|---|---|
| Dependency install | `py -m pip install -r requirements-dev.txt` | **Passed** | Python dependencies installed or already satisfied |
| Public dataset download | `py scripts/download_public_dataset.py` | **Passed** | 120 WPI records across 54 country codes written to `data/sample/world-port-index-sample.csv` |
| Frontend syntax | `node --check apps/web/app.js` | **Passed** | No JavaScript syntax errors |
| Python lint | `py -m ruff check apps tests scripts infrastructure/migrations/versions` | **Passed** | Zero findings after import-order fix |
| Python formatting | `py -m ruff format --check apps tests scripts infrastructure/migrations/versions` | **Passed** | 31 files already formatted |
| Type checking | `$env:PYTHONPATH='apps/api'; py -m mypy apps/api/harborvision` | **Passed** | No issues in 15 source files |
| Python compilation | `$env:PYTHONPATH='apps/api'; py -m compileall -q apps/api/harborvision scripts tests` | **Passed** | No compile errors |
| Dataset tests | `$env:PYTHONPATH='apps/api'; py -m pytest -q tests/test_public_dataset.py` | **Passed** | 3 passed |
| Backend tests | `$env:PYTHONPATH='apps/api'; py -m pytest -q` | **Passed with skip** | 31 passed, 1 skipped because Tesseract is not installed locally |
| Dependency consistency | `py -m pip check` | **Passed** | No broken requirements found |
| Fresh migration and seed | `py -m alembic upgrade head`; `py -m harborvision.seed` with a temp SQLite database | **Passed** | Alembic revisions `0001` and `0002` applied; deterministic seed inserted |
| Data integrity | `py scripts/data_integrity.py` against a seeded temp SQLite database | **Passed** | All integrity checks passed |
| Integrated verification | `$env:PYTHONPATH='apps/api'; py scripts/verify.py` | **Passed** | Public dataset endpoint returned 120 ports and 54 country codes; existing API, vision, reports, and integrity checks passed |
| Local API smoke | Uvicorn on `127.0.0.1:8017` with a SQLite database | **Passed** | Readiness 200, OpenAPI docs 200, login succeeded, dashboard reported 600 containers |
| Docker runtime | `docker --version` | **Not executed** | Docker is not installed on this host |
| Tesseract OCR runtime | `tesseract --version` | **Not executed** | Tesseract is not installed on PATH |
| Playwright browser install | `py -m playwright install chromium` | **Passed** | Managed Chromium downloaded for screenshot capture |
| Screenshot regeneration | `$env:HARBORVISION_LOCAL_API='http://127.0.0.1:8017'; py scripts/capture_screenshots.py` | **Passed** | 24 PNG screenshots captured from the locally running app, including the public dataset workflow |

## Fixes made during verification

- Normalized PyJWT token encoding defensively so the helper always returns `str`.
- Aligned package metadata, README, and deployment docs to Python 3.12+ because current CI and dependency stubs validate on Python 3.12.
- Added a clear `503` response for the OCR sample endpoint when Tesseract is unavailable.
- Made the OCR integration test skip only when the external Tesseract binary is missing.
- Added SQLite journal patterns to `.gitignore`.
- Made screenshot capture portable across system Chromium and Playwright-managed Chromium, with `HARBORVISION_LOCAL_API` support for alternate local ports.
- Removed stale README claims that repository publication could not be completed.
- Added a reproducible WPI downloader, processed public-domain sample, API endpoint, browser view, tests, README section, dataset documentation, and third-party notices.

## Deterministic seed evidence

The fresh seed produced:

| Entity | Count |
|---|---:|
| Organizations | 1 |
| Terminals | 1 |
| Users | 6 |
| Berths | 4 |
| Vessel calls | 6 |
| Yard blocks | 8 |
| Yard slots | 960 |
| Containers | 600 |
| Truck visits | 120 |
| Equipment assets | 20 |
| Equipment telemetry readings | 7,200 |
| Reefer readings | 1,728 |
| Cameras | 8 |

## Public dataset evidence

The WPI sample preparation produced:

| Item | Value |
|---|---:|
| Processed records | 120 |
| Distinct country codes | 54 |
| Large harbor records | 55 |
| Medium harbor records | 65 |

The integrated verifier called `/api/v1/public-dataset/ports?limit=10` and received HTTP 200 with the public-domain license string, sample count, country count, and ranked port records.

## Data-integrity results

Passed checks:

1. No container occupies two active slots.
2. No active slot is assigned to multiple containers.
3. Slot occupancy agrees with current container location.
4. Vessel timestamps are chronological.
5. Truck timestamps are chronological.
6. Reefer readings reference reefer containers.
7. Incident source references exist where required.
8. Organization ownership is consistent.
9. Current container location matches the latest accepted movement.

## Browser evidence

The repository includes 24 PNG screenshots under `docs/screenshots/`. They were regenerated on this Windows verification host from the implemented browser console connected to a locally running FastAPI application on `127.0.0.1:8017`, the deterministic NorthStar terminal database, and the committed WPI public-dataset sample.

## Limitations

1. Docker Compose runtime validation could not be executed because Docker is not installed on this host.
2. Tesseract-backed OCR could not be executed locally because the OCR binary is not installed on PATH. The API now returns a clear dependency error in that case, and CI installs Tesseract before running the OCR integration test.
3. PostgreSQL/PostGIS, Redis, and MinIO behavior is not claimed from the SQLite verification run.
4. Vision verification covers tracked motion and polygon rules, not semantic person, vehicle, PPE, or certified safety detection.
5. OCR results use generated samples and are not industrial field-accuracy evidence.
6. Predictive-maintenance outputs are engineering risk indicators, not guaranteed failure predictions.
