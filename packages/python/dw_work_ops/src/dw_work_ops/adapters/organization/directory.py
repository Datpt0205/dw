"""Organization directory backed by the platform membership tables.

Assignees are resolved against the system of record — never invented by the
model (blueprint §11.4).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_kernel.ids import UserId
from dw_platform.adapters.persistence import tables as platform_tables
from dw_work_ops.application.ports import DirectoryPerson

_SET_TENANT = text("SELECT set_config('app.tenant_id', :tenant_id, true)")


@dataclass(frozen=True)
class SqlOrganizationDirectory:
    """Implements ``OrganizationDirectoryPort``."""

    session_factory: async_sessionmaker[AsyncSession]

    async def list_people(self, tenant_id: uuid.UUID) -> list[DirectoryPerson]:
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"tenant_id": str(tenant_id)})
            rows = await session.execute(
                sa.select(
                    platform_tables.users.c.id,
                    platform_tables.users.c.display_name,
                    platform_tables.users.c.email,
                    platform_tables.memberships.c.department,
                )
                .select_from(
                    platform_tables.memberships.join(
                        platform_tables.users,
                        platform_tables.memberships.c.user_id == platform_tables.users.c.id,
                    )
                )
                .where(platform_tables.memberships.c.tenant_id == tenant_id)
            )
        return [
            DirectoryPerson(
                person_id=UserId(row.id),
                display_name=row.display_name,
                department=row.department,
                email=row.email,
            )
            for row in rows
        ]
