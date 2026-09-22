"""Runtime configuration.

Everything comes from environment variables with local-development defaults,
so `docker compose up` and a bare `uvicorn` on a laptop both work without a
config file. Nothing here is a secret: the only credentials are for local
services, and the optional feed keys are read but never logged.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _env(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


@dataclass(frozen=True, slots=True)
class Settings:
    env: str = field(default_factory=lambda: _env("ONSIDE_ENV", "local"))
    table: str = field(default_factory=lambda: _env("ONSIDE_TABLE", "onside"))
    dynamo_endpoint: str = field(
        default_factory=lambda: _env("ONSIDE_DYNAMO_ENDPOINT", "http://localhost:8000")
    )
    region: str = field(default_factory=lambda: _env("AWS_DEFAULT_REGION", "us-east-1"))
    redis_url: str = field(
        default_factory=lambda: _env("ONSIDE_REDIS_URL", "redis://localhost:6379/0")
    )
    archive_uri: str = field(
        default_factory=lambda: _env(
            "ONSIDE_ARCHIVE_URI", str(ROOT / "data" / "archive" / "events")
        )
    )
    s3_endpoint: str = field(
        default_factory=lambda: _env("ONSIDE_S3_ENDPOINT", "http://localhost:9000")
    )
    data_dir: Path = field(
        default_factory=lambda: Path(_env("ONSIDE_DATA_DIR", str(ROOT / "data")))
    )
    model_dir: Path = field(
        default_factory=lambda: Path(_env("ONSIDE_MODEL_DIR", str(ROOT / "models")))
    )
    football_data_key: str = field(
        default_factory=lambda: os.environ.get("FOOTBALL_DATA_API_KEY", "")
    )
    api_football_key: str = field(default_factory=lambda: os.environ.get("API_FOOTBALL_KEY", ""))
    # Social sources. Mastodon needs nothing; the rest switch on with a key.
    mastodon_instance: str = field(
        default_factory=lambda: _env("MASTODON_INSTANCE", "https://mastodon.social")
    )
    bluesky_handle: str = field(
        default_factory=lambda: os.environ.get("BLUESKY_HANDLE", "").strip()
    )
    bluesky_app_password: str = field(
        default_factory=lambda: os.environ.get("BLUESKY_APP_PASSWORD", "").strip()
    )
    reddit_client_id: str = field(
        default_factory=lambda: os.environ.get("REDDIT_CLIENT_ID", "").strip()
    )
    reddit_client_secret: str = field(
        default_factory=lambda: os.environ.get("REDDIT_CLIENT_SECRET", "").strip()
    )
    x_bearer_token: str = field(
        default_factory=lambda: os.environ.get("X_BEARER_TOKEN", "").strip()
    )
    x_max_reads_per_day: int = field(default_factory=lambda: int(_env("X_MAX_READS_PER_DAY", "0")))
    cors_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            _env("ONSIDE_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
        )
    )

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def match_docs_dir(self) -> Path:
        return self.processed_dir / "matches"

    @property
    def archive_is_s3(self) -> bool:
        return self.archive_uri.startswith("s3://")

    @property
    def is_local(self) -> bool:
        return self.env in ("local", "test")


@lru_cache(maxsize=1)
def settings() -> Settings:
    return Settings()
