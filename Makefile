PYTHONPATH := apps/api
PYTHON := python

.PHONY: setup dev up down logs migrate migrate-check seed reset test test-backend test-frontend test-e2e lint format format-check typecheck build verify data-integrity ocr-evaluate runtime-evidence security-scan screenshots walkthrough package clean

setup:
	$(PYTHON) -m pip install -r requirements-dev.txt
	cp -n .env.example .env || true

migrate:
	PYTHONPATH=$(PYTHONPATH) alembic upgrade head

migrate-check:
	rm -f /tmp/harborvision-migration-check.db
	DATABASE_URL=sqlite:////tmp/harborvision-migration-check.db PYTHONPATH=$(PYTHONPATH) alembic upgrade head
	DATABASE_URL=sqlite:////tmp/harborvision-migration-check.db PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m harborvision.seed

seed:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m harborvision.seed

reset: seed

dev:
	PYTHONPATH=$(PYTHONPATH) uvicorn harborvision.main:app --reload --port 8000

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

test test-backend:
	PYTHONPATH=$(PYTHONPATH) pytest

test-frontend:
	node --check apps/web/app.js

test-e2e:
	PYTHONPATH=$(PYTHONPATH):scripts $(PYTHON) scripts/capture_screenshots.py

lint:
	ruff check apps tests scripts infrastructure/migrations/versions

format:
	ruff format apps tests scripts infrastructure/migrations/versions

format-check:
	ruff format --check apps tests scripts infrastructure/migrations/versions

typecheck:
	PYTHONPATH=$(PYTHONPATH) mypy apps/api/harborvision

build:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m compileall -q apps/api/harborvision scripts tests
	node --check apps/web/app.js

data-integrity:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/data_integrity.py

ocr-evaluate:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/ocr_evaluate.py

runtime-evidence:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/generate_real_runtime_evidence.py

security-scan:
	$(PYTHON) scripts/secret_scan.py

verify:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/verify.py

screenshots:
	PYTHONPATH=$(PYTHONPATH):scripts $(PYTHON) scripts/capture_screenshots.py

walkthrough:
	PYTHONPATH=$(PYTHONPATH):scripts $(PYTHON) scripts/record_walkthrough.py

package:
	bash scripts/package.sh

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage harborvision.db
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
