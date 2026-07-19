# Operations Runbook

## Start

```bash
cp .env.example .env
PYTHONPATH=apps/api python -m harborvision.seed
PYTHONPATH=apps/api uvicorn harborvision.main:app --host 0.0.0.0 --port 8000
```

## Stop

Stop the Uvicorn process with `Ctrl+C`. In Docker:

```bash
docker compose down
```

## Reset demonstration data

```bash
make seed
```

This drops and recreates all tables and regenerates sample media.

## Migrations

```bash
PYTHONPATH=apps/api alembic upgrade head
PYTHONPATH=apps/api alembic current
```

Back up the database before production migrations.

## Backup and restore

SQLite:

```bash
cp harborvision.db backups/harborvision-$(date +%F-%H%M).db
cp backups/<file>.db harborvision.db
```

PostgreSQL:

```bash
docker compose exec postgres pg_dump -U harborvision harborvision > backup.sql
cat backup.sql | docker compose exec -T postgres psql -U harborvision harborvision
```

Evidence and reports are under `data/generated` locally or the named Docker volume.

## Worker recovery

```bash
docker compose restart worker
docker compose logs --tail=200 worker
```

Check `data/generated/worker-heartbeat.json`.

## Camera recovery

1. Verify the configured source exists and is readable.
2. Run `POST /api/v1/vision/process-sample` with a safety/admin/director token.
3. Check API logs and `data/generated/annotated`.
4. Confirm a new event under `/api/v1/safety-events`.
5. Confirm evidence under `data/generated/evidence`.

## Database health

```bash
curl http://localhost:8000/api/v1/health/ready
```

## Log inspection

Local logs are emitted as structured JSON-like records to stdout. Docker:

```bash
docker compose logs -f --tail=200 api worker
```

## Verification

```bash
make test
make build
make verify
```

Results are written to `docs/verification-results.json`.
