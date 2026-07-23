"""Composition root: the only place concrete adapters are wired together.

Tests build their own container with fake ports; production wiring lives here.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from dw_api.health import HealthService, database_probe
from dw_api.settings import ApiSettings
from dw_platform.adapters.identity.dev_token import DevTokenVerifier
from dw_platform.adapters.identity.keycloak import KeycloakTokenVerifier
from dw_platform.adapters.persistence.membership_lookup import SqlMembershipLookup
from dw_platform.adapters.persistence.uow import SqlPlatformUnitOfWorkFactory
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.entitlement import DEFAULT_PLANS, PlanEntitlementService
from dw_platform.application.identity import DbAccessContextFactory
from dw_platform.application.ports import (
    AccessContextFactoryPort,
    PlatformUnitOfWorkFactory,
    TokenVerifierPort,
)


@dataclass
class ApiContainer:
    """Wired dependencies for the API process."""

    settings: ApiSettings
    engine: AsyncEngine | None
    health_service: HealthService
    token_verifier: TokenVerifierPort | None
    access_context_factory: AccessContextFactoryPort | None
    uow_factory: PlatformUnitOfWorkFactory | None
    authorization: ScopeAuthorizationService
    entitlement: PlanEntitlementService

    async def shutdown(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()


def _build_token_verifier(settings: ApiSettings) -> TokenVerifierPort | None:
    if settings.auth_mode == "oidc":
        assert settings.oidc_issuer_url is not None  # validate_for_profile enforced
        return KeycloakTokenVerifier(settings.oidc_issuer_url, settings.oidc_audience)
    if settings.dev_secret:
        return DevTokenVerifier(settings.dev_secret)
    return None  # auth disabled until a secret is configured (local only)


def build_container(settings: ApiSettings | None = None) -> ApiContainer:
    settings = settings or ApiSettings()
    settings.validate_for_profile()

    engine: AsyncEngine | None = None
    access_context_factory: AccessContextFactoryPort | None = None
    uow_factory: PlatformUnitOfWorkFactory | None = None

    if settings.database_url:
        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        access_context_factory = DbAccessContextFactory(SqlMembershipLookup(session_factory))
        uow_factory = SqlPlatformUnitOfWorkFactory(session_factory)

    return ApiContainer(
        settings=settings,
        engine=engine,
        health_service=HealthService(probes={"database": database_probe(engine)}),
        token_verifier=_build_token_verifier(settings),
        access_context_factory=access_context_factory,
        uow_factory=uow_factory,
        authorization=ScopeAuthorizationService(),
        entitlement=PlanEntitlementService(DEFAULT_PLANS),
    )
