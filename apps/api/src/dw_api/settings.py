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

    # --- model provider (ADR-012) ---
    model_provider: str = Field(
        default="mock", validation_alias=AliasChoices("DW_API_MODEL_PROVIDER", "DW_MODEL_PROVIDER")
    )
    openai_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("DW_API_OPENAI_API_KEY", "OPENAI_API_KEY")
    )
    openai_base_url: str | None = Field(
        default=None, validation_alias=AliasChoices("DW_API_OPENAI_BASE_URL", "OPENAI_BASE_URL")
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
