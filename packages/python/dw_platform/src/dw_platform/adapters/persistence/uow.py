"""SQL Unit of Work binding the trusted tenant context per transaction.

`SET LOCAL` (via ``set_config(..., is_local => true)``) scopes the RLS context
to the current transaction only — connections returned to the pool carry no
tenant state (blueprint §15.3).
"""

from __future__ import annotations

from dataclasses import dataclass
from types import TracebackType

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_kernel.errors import TenantContextMissingError
from dw_platform.adapters.persistence.repositories import (
    SqlApprovalRepository,
    SqlAuditRepository,
    SqlOutboxRepository,
)
from dw_platform.application.access_context import AccessContext
from dw_platform.application.ports import (
    ApprovalRepositoryPort,
    AuditRepositoryPort,
    OutboxRepositoryPort,
)

_SET_CONFIG = text(
    "SELECT set_config('app.tenant_id', :tenant_id, true),"
    "       set_config('app.workspace_id', :workspace_id, true),"
    "       set_config('app.user_id', :user_id, true)"
)


async def apply_tenant_context(session: AsyncSession, context: AccessContext) -> None:
    """Apply SET LOCAL tenant context inside the session's open transaction."""
    await session.execute(
        _SET_CONFIG,
        {
            "tenant_id": str(context.tenant_id),
            "workspace_id": str(context.workspace_id),
            "user_id": str(context.principal_id),
        },
    )


class SqlPlatformUnitOfWork:
    """Implements ``PlatformUnitOfWork`` over one AsyncSession transaction."""

    approvals: ApprovalRepositoryPort
    audit: AuditRepositoryPort
    outbox: OutboxRepositoryPort

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        context: AccessContext,
    ) -> None:
        if context is None:  # defensive: never run tenant-scoped SQL without context
            raise TenantContextMissingError("UnitOfWork requires an AccessContext")
        self._session_factory = session_factory
        self._context = context
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> SqlPlatformUnitOfWork:
        self._session = self._session_factory()
        await self._session.begin()
        await apply_tenant_context(self._session, self._context)
        self.approvals = SqlApprovalRepository(self._session)
        self.audit = SqlAuditRepository(self._session)
        self.outbox = SqlOutboxRepository(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        assert self._session is not None
        try:
            if exc_type is not None:
                await self._session.rollback()
        finally:
            await self._session.close()
            self._session = None

    async def commit(self) -> None:
        assert self._session is not None, "UoW not entered"
        await self._session.commit()

    async def rollback(self) -> None:
        assert self._session is not None, "UoW not entered"
        await self._session.rollback()


@dataclass(frozen=True)
class SqlPlatformUnitOfWorkFactory:
    """Implements ``PlatformUnitOfWorkFactory``."""

    session_factory: async_sessionmaker[AsyncSession]

    def __call__(self, context: AccessContext) -> SqlPlatformUnitOfWork:
        return SqlPlatformUnitOfWork(self.session_factory, context)
