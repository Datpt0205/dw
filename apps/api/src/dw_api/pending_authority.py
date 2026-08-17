"""Reads back who a pending checkpoint is reserved for.

The workflow stamps ``required_role`` onto each approval request from the
versioned rule pack, and ``approval_flow`` refuses anyone who does not hold it.
Anything that tells a person "this is waiting for you" has to read that same
stamp — otherwise chat invites a decision the API then rejects, which is worse
than saying nothing. Role display names come from the ``roles`` table so they
are spelled in exactly one place.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_platform.adapters.persistence import tables
from dw_platform.application.access_context import AccessContext
from dw_platform.application.ports import PlatformUnitOfWorkFactory
from dw_tender.application.conversation.service import PendingAuthority


@dataclass(frozen=True)
class SqlPendingAuthority:
    """Implements ``PendingAuthorityPort``."""

    uow_factory: PlatformUnitOfWorkFactory
    session_factory: async_sessionmaker[AsyncSession]

    async def by_case(self, context: AccessContext) -> dict[uuid.UUID, PendingAuthority]:
        async with self.uow_factory(context) as uow:
            pending = await uow.approvals.list_pending()

        stamped: dict[uuid.UUID, str] = {}
        for request in pending:
            role = str(request.payload.get("required_role", "") or "")
            raw_case_id = str(request.payload.get("case_id", "") or "")
            if not role or not raw_case_id:
                continue
            try:
                stamped[uuid.UUID(raw_case_id)] = role
            except ValueError:
                continue
        if not stamped:
            return {}

        names = await self._role_names(set(stamped.values()))
        return {
            case_id: PendingAuthority(role_key=role, role_name=names.get(role, role))
            for case_id, role in stamped.items()
        }

    async def _role_names(self, keys: set[str]) -> dict[str, str]:
        async with self.session_factory() as session:
            rows = await session.execute(
                sa.select(tables.roles.c.key, tables.roles.c.name).where(
                    tables.roles.c.key.in_(keys)
                )
            )
            return {row.key: row.name for row in rows}
