"""Runtime settings; secrets only via environment (never hardcoded)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

Profile = Literal["local", "test", "production"]


class ApiSettings(BaseSettings):
    """API process configuration, validated at startup.

    In the production profile unknown critical conditions fail fast; mocks are
    forbidden there (ADR-012).
    """

    model_config = SettingsConfigDict(env_prefix="DW_API_", extra="ignore")

    profile: Profile = "local"
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)
    database_url: str | None = None
    cors_origins: list[str] = []

    def require_database_url(self) -> str:
        if not self.database_url:
            raise RuntimeError(
                "DW_API_DATABASE_URL is not configured; the API cannot serve tenant data"
            )
        return self.database_url
