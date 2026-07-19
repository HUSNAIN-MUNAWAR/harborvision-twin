# Deployment

## Local development

Requirements:

- Python 3.12 or newer;
- Tesseract OCR;
- system libraries required by OpenCV;
- Node.js only for the JavaScript syntax check and optional tooling.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
PYTHONPATH=apps/api alembic upgrade head
PYTHONPATH=apps/api python -m harborvision.seed
PYTHONPATH=apps/api uvicorn harborvision.main:app --port 8000
```

The FastAPI process serves both the API and the zero-build web console at `http://localhost:8000`.

## Docker topology

`docker-compose.yml` defines:

- PostGIS/PostgreSQL for primary persistence;
- Redis for shared coordination/readiness;
- MinIO as an optional object-storage service;
- API container;
- separable worker heartbeat container;
- Nginx web container.

```bash
cp .env.example .env
# replace all local-only secrets

docker compose config
docker compose up --build -d
docker compose exec api alembic upgrade head
docker compose exec api python -m harborvision.seed
docker compose ps
```

## Configuration contract

See `.env.example`. Production startup rejects an undersized JWT secret and the default development secret. CORS origins are explicit. No real `.env` file belongs in source control.

## Health

- `/api/v1/health/live`: process liveness.
- `/api/v1/health/ready`: database query, storage write probe, Redis state, worker-heartbeat age, and environment label.

Redis is optional in local development and required only when the deployment policy marks it required.

## Production additions

A real port deployment needs TLS termination, an external identity provider, a secrets manager, encrypted backups, HA databases, object-storage lifecycle rules, network segmentation, log aggregation, metrics, alerting, TOS/PLC/SCADA adapters, and disaster-recovery testing.
