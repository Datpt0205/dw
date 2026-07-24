"""Worker process settings."""

from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DW_WORKER_", extra="ignore")

    heartbeat_file: Path = Path("/tmp/dw-worker-heartbeat")
    heartbeat_interval_seconds: float = Field(default=5.0, gt=0, le=60)
    poll_interval_seconds: float = Field(default=1.0, gt=0, le=60)

    # Infrastructure for the knowledge ingest consumer (B5). Aliases accept the
    # same plain env vars the compose stack already provides. When database_url /
    # s3_endpoint_url are unset, the consumer is skipped (heartbeat-only worker).
    database_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DW_WORKER_DATABASE_URL", "DW_DATABASE_URL"),
    )
    qdrant_url: str | None = Field(
        default=None, validation_alias=AliasChoices("DW_WORKER_QDRANT_URL", "QDRANT_URL")
    )
    s3_endpoint_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DW_WORKER_S3_ENDPOINT_URL", "S3_ENDPOINT_URL"),
    )
    s3_access_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DW_WORKER_S3_ACCESS_KEY", "MINIO_ROOT_USER"),
    )
    s3_secret_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DW_WORKER_S3_SECRET_KEY", "MINIO_ROOT_PASSWORD"),
    )
    s3_bucket: str = Field(
        default="dw-artifacts",
        validation_alias=AliasChoices("DW_WORKER_S3_BUCKET", "S3_BUCKET_ARTIFACTS"),
    )

    embedding_provider: str = Field(
        default="hash", validation_alias=AliasChoices("DW_WORKER_EMBEDDING_PROVIDER")
    )
    embed_url: str | None = Field(
        default=None, validation_alias=AliasChoices("DW_WORKER_EMBED_URL", "TEI_EMBED_URL")
    )
    rerank_url: str | None = Field(
        default=None, validation_alias=AliasChoices("DW_WORKER_RERANK_URL", "TEI_RERANK_URL")
    )
    embed_dimension: int = Field(
        default=1024, validation_alias=AliasChoices("DW_WORKER_EMBED_DIMENSION")
    )

    # How many queued jobs to drain per poll tick.
    ingest_batch_size: int = Field(default=1, ge=1, le=16)
