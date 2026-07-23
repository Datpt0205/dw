"""Composition root: the only place concrete adapters are wired together.

Tests build their own app with fake probes; production wiring lives here.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from dw_api.health import HealthService, database_probe
from dw_api.settings import ApiSettings


@dataclass
class ApiContainer:
    """Wired dependencies for the API process."""

    settings: ApiSettings
    engine: AsyncEngine | None
    health_service: HealthService

    async def shutdown(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()


def build_container(settings: ApiSettings | None = None) -> ApiContainer:
    settings = settings or ApiSettings()

    engine: AsyncEngine | None = None
    if settings.database_url:
        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    elif settings.profile == "production":
        # Production must fail fast instead of silently running without a DB.
        settings.require_database_url()

    health_service = HealthService(probes={"database": database_probe(engine)})
    return ApiContainer(settings=settings, engine=engine, health_service=health_service)
