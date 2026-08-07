"""Worker process settings."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DW_WORKER_",
        extra="ignore",
        populate_by_name=True,
    )

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

    # Durable DW01 approval notifications. Slack member IDs are deliberately
    # configuration, never guessed from display names or committed to source.
    slack_approvals_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "DW_WORKER_SLACK_APPROVALS_ENABLED", "DW_SLACK_APPROVALS_ENABLED"
        ),
    )
    slack_bot_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DW_WORKER_SLACK_BOT_TOKEN", "SLACK_BOT_TOKEN"),
    )
    slack_web_base_url: str = Field(
        default="http://localhost:3000",
        validation_alias=AliasChoices("DW_WORKER_SLACK_WEB_BASE_URL", "DW_PUBLIC_WEB_URL"),
    )
    slack_user_map_json: str = Field(
        default="",
        validation_alias=AliasChoices("DW_WORKER_SLACK_USER_MAP_JSON", "SLACK_USER_MAP_JSON"),
    )
    slack_user_an_id: str = Field(default="", validation_alias=AliasChoices("SLACK_USER_AN_ID"))
    slack_user_binh_id: str = Field(default="", validation_alias=AliasChoices("SLACK_USER_BINH_ID"))
    slack_user_chi_id: str = Field(default="", validation_alias=AliasChoices("SLACK_USER_CHI_ID"))

    def slack_user_map(self) -> dict[str, str]:
        mapping = {
            "dev|an.nguyen": self.slack_user_an_id.strip(),
            "dev|binh.tran": self.slack_user_binh_id.strip(),
            "dev|chi.le": self.slack_user_chi_id.strip(),
        }
        if self.slack_user_map_json.strip():
            raw = json.loads(self.slack_user_map_json)
            if not isinstance(raw, dict):
                raise RuntimeError("SLACK_USER_MAP_JSON must be a JSON object")
            mapping.update({str(key): str(value).strip() for key, value in raw.items()})
        return {key: value for key, value in mapping.items() if value}

    # Which chat channel receives approval cards: "slack" (buttons) or
    # "zalo" (plain words parsed by the API-side DecisionEngine).
    approval_channel: str = Field(
        default="slack", validation_alias=AliasChoices("DW_APPROVAL_CHANNEL")
    )
    zalo_bot_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DW_WORKER_ZALO_BOT_TOKEN", "ZALO_BOT_TOKEN"),
    )
    zalo_user_an_id: str = Field(default="", validation_alias=AliasChoices("ZALO_USER_AN_ID"))
    zalo_user_binh_id: str = Field(default="", validation_alias=AliasChoices("ZALO_USER_BINH_ID"))
    zalo_user_chi_id: str = Field(default="", validation_alias=AliasChoices("ZALO_USER_CHI_ID"))
    zalo_user_map_json: str = Field(default="", validation_alias=AliasChoices("ZALO_USER_MAP_JSON"))

    def zalo_user_map(self) -> dict[str, str]:
        mapping = {
            "dev|an.nguyen": self.zalo_user_an_id.strip(),
            "dev|binh.tran": self.zalo_user_binh_id.strip(),
            "dev|chi.le": self.zalo_user_chi_id.strip(),
        }
        if self.zalo_user_map_json.strip():
            raw = json.loads(self.zalo_user_map_json)
            if not isinstance(raw, dict):
                raise RuntimeError("ZALO_USER_MAP_JSON must be a JSON object")
            mapping.update({str(key): str(value).strip() for key, value in raw.items()})
        return {key: value for key, value in mapping.items() if value}

    def validate_slack(self) -> None:
        if not self.slack_approvals_enabled:
            return
        if not self.database_url:
            raise RuntimeError("Slack approvals require DW_WORKER_DATABASE_URL")
        if self.approval_channel == "zalo":
            if not self.zalo_bot_token:
                raise RuntimeError("Zalo approvals require ZALO_BOT_TOKEN")
            if "dev|binh.tran" not in self.zalo_user_map():
                raise RuntimeError("Zalo approvals require ZALO_USER_BINH_ID (approver)")
            return
        if not self.slack_bot_token or not self.slack_bot_token.startswith("xoxb-"):
            raise RuntimeError("Slack approvals require a Bot User OAuth Token (xoxb-...)")
        mapping = self.slack_user_map()
        missing = [
            subject
            for subject in ("dev|an.nguyen", "dev|binh.tran", "dev|chi.le")
            if subject not in mapping
        ]
        if missing:
            raise RuntimeError(
                "Slack approvals require member ID mappings for: " + ", ".join(missing)
            )
