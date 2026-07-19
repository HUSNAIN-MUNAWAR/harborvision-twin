from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _csv_env(name: str, default: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in os.getenv(name, default).split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    """Validated runtime configuration shared by API and worker processes."""

    app_name: str = "HarborVision Twin"
    api_prefix: str = "/api/v1"
    environment: str = os.getenv("ENVIRONMENT", "development").lower()
    database_url: str = os.getenv("DATABASE_URL", f"sqlite:///{ROOT / 'harborvision.db'}")
    redis_url: str | None = os.getenv("REDIS_URL") or None
    jwt_secret: str = os.getenv("JWT_SECRET", "development-only-change-me-use-32-bytes-minimum")
    jwt_algorithm: str = "HS256"
    token_minutes: int = int(os.getenv("TOKEN_MINUTES", "480"))
    refresh_token_days: int = int(os.getenv("REFRESH_TOKEN_DAYS", "14"))
    storage_dir: Path = Path(os.getenv("STORAGE_DIR", str(ROOT / "data" / "generated")))
    cors_origins: tuple[str, ...] = _csv_env("CORS_ORIGINS", "http://localhost:8000,http://localhost:3000")
    max_image_bytes: int = int(os.getenv("MAX_IMAGE_BYTES", str(10 * 1024 * 1024)))
    max_video_bytes: int = int(os.getenv("MAX_VIDEO_BYTES", str(250 * 1024 * 1024)))
    worker_stale_seconds: int = int(os.getenv("WORKER_STALE_SECONDS", "120"))

    def __post_init__(self) -> None:
        if self.environment not in {"development", "test", "production"}:
            raise ValueError("ENVIRONMENT must be development, test, or production")
        if len(self.jwt_secret.encode()) < 32:
            raise ValueError("JWT_SECRET must contain at least 32 bytes")
        if self.token_minutes < 1:
            raise ValueError("TOKEN_MINUTES must be positive")
        if self.refresh_token_days < 1:
            raise ValueError("REFRESH_TOKEN_DAYS must be positive")
        if self.environment == "production" and self.jwt_secret.startswith("development-only"):
            raise ValueError("Production requires a non-default JWT_SECRET")
        if not self.cors_origins:
            raise ValueError("At least one explicit CORS origin is required")


settings = Settings()
settings.storage_dir.mkdir(parents=True, exist_ok=True)
