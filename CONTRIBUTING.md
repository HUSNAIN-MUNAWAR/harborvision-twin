# Contributing to HarborVision Twin

## Before opening a change

Discuss large domain, schema, vision-model, or deployment changes in an issue. Explain the operational workflow, tenancy boundary, validation method, and licensing impact.

## Local workflow

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
make migrate
make seed
make test
make lint
make format-check
make typecheck
make test-frontend
make data-integrity
make security-scan
```

## Engineering standards

- Keep organization scope in every operational query and mutation.
- Move business rules into testable services rather than route handlers.
- Keep event application idempotent and transactional.
- Preserve append-only movement, note, and audit history where documented.
- Derive metrics from source records.
- Label synthetic/demo data and estimated values.
- Never claim a model, build, test, benchmark, or deployment was verified unless it was run.
- Add failure-path tests for permissions, conflicts, stale events, and invalid transitions.

## Assets and data

Do not contribute proprietary terminal maps, customer/container data, personal information, private camera media, credentials, or unlicensed model weights. Document model and asset licenses.

## Commit and pull-request style

Use focused conventional commits, for example:

```text
feat: add historical twin event projection
fix: reject cross-tenant yard slot mutation
test: cover reefer escalation duration
docs: document OCR evidence lifecycle
```

The pull request must list exact validation commands and relevant results.
