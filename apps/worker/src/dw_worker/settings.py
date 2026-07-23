"""Worker process settings."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DW_WORKER_", extra="ignore")

    heartbeat_file: Path = Path("/tmp/dw-worker-heartbeat")
    heartbeat_interval_seconds: float = Field(default=5.0, gt=0, le=60)
    poll_interval_seconds: float = Field(default=1.0, gt=0, le=60)
