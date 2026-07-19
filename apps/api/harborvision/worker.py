from __future__ import annotations

import json
import logging
import os
import time
from datetime import UTC, datetime

from sqlalchemy import func, select

from .config import settings
from .database import SessionLocal
from .models import OperationalEvent

logging.basicConfig(level=logging.INFO, format='{"time":"%(asctime)s","level":"%(levelname)s","message":"%(message)s"}')
logger = logging.getLogger("harborvision.worker")


def heartbeat() -> dict:
    with SessionLocal() as db:
        event_count = db.scalar(select(func.count()).select_from(OperationalEvent)) or 0
    payload = {"status": "alive", "time": datetime.now(UTC).isoformat(), "event_count": event_count}
    path = settings.storage_dir / "worker-heartbeat.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def main() -> None:
    interval = max(5, int(os.getenv("WORKER_HEARTBEAT_SECONDS", "30")))
    logger.info("worker started interval=%s", interval)
    while True:
        logger.info("heartbeat %s", heartbeat())
        time.sleep(interval)


if __name__ == "__main__":
    main()
