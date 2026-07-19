# Troubleshooting

## Tesseract is missing

Install `tesseract-ocr` and ensure `tesseract --version` succeeds. The API returns an OCR error rather than fabricating a result.

## OpenCV cannot open the sample MP4

Run `make seed` to regenerate the video. Confirm `data/sample/restricted-zone-demo.mp4` exists and the host has video codec support.

## Empty dashboard

Run `PYTHONPATH=apps/api python -m harborvision.seed`. The application also seeds an empty database on startup.

## Login fails

Use the documented local password. After repeated failures, wait five minutes or restart the local process to clear the in-memory development throttle.

## PostgreSQL connection failure

Verify the `DATABASE_URL`, database health, credentials, and the `postgres` service name. Run `docker compose ps` and `docker compose logs postgres`.

## Browser shows reconnecting

The SSE access token may have expired or the API may be restarting. Sign out and in, check `/api/v1/health/live`, and inspect browser network requests.

## Evidence URL returns 404

Run the video processor and confirm the path returned in the event. The static mount is `/artifacts` and maps to `data/generated`.

## Alembic reports existing tables

The local seed intentionally creates schema directly for zero-step startup. For a clean migration exercise, use a new database file or PostgreSQL database, run `alembic upgrade head`, then seed.
