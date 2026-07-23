"""Runtime settings; secrets only via environment (never hardcoded)."""

from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

Profile = Literal["local", "test", "production"]
AuthMode = Literal["dev", "oidc"]


class ApiSettings(BaseSettings):
    """API process configuration, validated at startup.

    In the production profile unknown critical conditions fail fast; mocks and
    the dev identity adapter are forbidden there (ADR-012, ADR-013).
    """

    model_config = SettingsConfigDict(env_prefix="DW_API_", extra="ignore", populate_by_name=True)

    profile: Profile = "local"
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)
    database_url: str | None = None
    cors_origins: list[str] = []

    # --- authentication (ADR-013) ---
    auth_mode: AuthMode = "dev"
    dev_secret: str | None = None
    oidc_issuer_url: str | None = None
    oidc_audience: str = "dw-api"

    # --- artifact storage (MinIO/S3) ---
    s3_endpoint_url: str | None = Field(
        default=None, validation_alias=AliasChoices("DW_API_S3_ENDPOINT_URL", "S3_ENDPOINT_URL")
    )
    s3_access_key: str | None = Field(
        default=None, validation_alias=AliasChoices("DW_API_S3_ACCESS_KEY", "MINIO_ROOT_USER")
    )
    s3_secret_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DW_API_S3_SECRET_KEY", "MINIO_ROOT_PASSWORD"),
    )
    s3_bucket: str = Field(
        default="dw-artifacts",
        validation_alias=AliasChoices("DW_API_S3_BUCKET", "S3_BUCKET_ARTIFACTS"),
    )

    # --- vector store ---
    qdrant_url: str | None = Field(
        default=None, validation_alias=AliasChoices("DW_API_QDRANT_URL", "QDRANT_URL")
    )

    # --- model provider (ADR-012) ---
    model_profile: str = Field(
        default="balanced",
        validation_alias=AliasChoices("DW_API_MODEL_PROFILE", "DW_MODEL_PROFILE_ID"),
    )
    openai_structured_mode: str = Field(
        default="json_schema",
        validation_alias=AliasChoices("DW_API_OPENAI_STRUCTURED_MODE"),
    )
    model_provider: str = Field(
        default="mock", validation_alias=AliasChoices("DW_API_MODEL_PROVIDER", "DW_MODEL_PROVIDER")
    )
    openai_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("DW_API_OPENAI_API_KEY", "OPENAI_API_KEY")
    )
    openai_base_url: str | None = Field(
        default=None, validation_alias=AliasChoices("DW_API_OPENAI_BASE_URL", "OPENAI_BASE_URL")
    )

    # --- hardening ---
    rate_limit_per_minute: int = Field(
        default=240,
        ge=0,  # 0 disables (tests); per-caller fixed window
        validation_alias=AliasChoices("DW_API_RATE_LIMIT_PER_MINUTE"),
    )
    outbound_allowed_hosts: list[str] = Field(
        default=[],
        validation_alias=AliasChoices("DW_API_OUTBOUND_ALLOWED_HOSTS"),
    )

    def outbound_allow_private(self) -> bool:
        """Local/test may call localhost providers (Ollama, vLLM); prod never."""
        return self.profile != "production"

    # --- channels & connectors (phase 7) ---
    task_connector: str = Field(
        default="mock",
        validation_alias=AliasChoices("DW_API_TASK_CONNECTOR", "DW_TASK_CONNECTOR"),
    )
    slack_bot_token: str | None = Field(
        default=None, validation_alias=AliasChoices("DW_API_SLACK_BOT_TOKEN", "SLACK_BOT_TOKEN")
    )
    slack_default_channel: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DW_API_SLACK_DEFAULT_CHANNEL", "SLACK_DEFAULT_CHANNEL"),
    )
    telegram_bot_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DW_API_TELEGRAM_BOT_TOKEN", "TELEGRAM_BOT_TOKEN"),
    )

    # --- observability (§21; Langfuse optional behind configuration) ---
    otel_endpoint: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DW_API_OTEL_ENDPOINT", "OTEL_EXPORTER_OTLP_ENDPOINT"),
    )
    langfuse_enabled: bool = Field(
        default=False, validation_alias=AliasChoices("DW_API_LANGFUSE_ENABLED", "LANGFUSE_ENABLED")
    )
    langfuse_host: str | None = Field(
        default=None, validation_alias=AliasChoices("DW_API_LANGFUSE_HOST", "LANGFUSE_HOST")
    )
    langfuse_public_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DW_API_LANGFUSE_PUBLIC_KEY", "LANGFUSE_PUBLIC_KEY"),
    )
    langfuse_secret_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DW_API_LANGFUSE_SECRET_KEY", "LANGFUSE_SECRET_KEY"),
    )

    def require_database_url(self) -> str:
        if not self.database_url:
            raise RuntimeError(
                "DW_API_DATABASE_URL is not configured; the API cannot serve tenant data"
            )
        return self.database_url

    def validate_for_profile(self) -> None:
        """Fail fast on configurations that must never reach production."""
        if self.profile == "production":
            if self.auth_mode == "dev":
                raise RuntimeError("dev auth mode is forbidden in the production profile")
            if not self.oidc_issuer_url:
                raise RuntimeError("OIDC issuer must be configured in production")
            self.require_database_url()
        if self.auth_mode == "oidc" and not self.oidc_issuer_url:
            raise RuntimeError("auth_mode=oidc requires DW_API_OIDC_ISSUER_URL")
        if self.langfuse_enabled and not (
            self.langfuse_host and self.langfuse_public_key and self.langfuse_secret_key
        ):
            raise RuntimeError(
                "LANGFUSE_ENABLED requires LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY "
                "and LANGFUSE_SECRET_KEY"
            )
        if self.task_connector not in ("mock", "slack"):
            raise RuntimeError("DW_TASK_CONNECTOR must be 'mock' or 'slack'")
        if self.task_connector == "slack" and not (
            self.slack_bot_token and self.slack_default_channel
        ):
            raise RuntimeError(
                "DW_TASK_CONNECTOR=slack requires SLACK_BOT_TOKEN and SLACK_DEFAULT_CHANNEL"
            )
        if self.profile == "production" and self.task_connector == "mock":
            raise RuntimeError("the mock task connector is forbidden in production")
