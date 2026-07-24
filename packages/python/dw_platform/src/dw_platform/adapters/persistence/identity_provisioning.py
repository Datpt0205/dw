"""SQL implementation of identity bootstrap + first-login provisioning.

Runs as the RLS-constrained runtime role (``dw_app``). The identity plane
(``users``, ``external_identities``) has no RLS; membership reads/writes set the
default tenant as the RLS context first, so a brand-new user can only ever be
provisioned into that one tenant.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_platform.adapters.persistence import tables
from dw_platform.application.identity_bootstrap import (
    BootstrapView,
    WorkspaceMembershipView,
)
from dw_platform.application.ports import VerifiedIdentity

_SET_TENANT = text("SELECT set_config('app.tenant_id', :tenant_id, true)")


def _display_name_for(identity: VerifiedIdentity) -> str:
    name = getattr(identity, "name", None)
    if name:
        return str(name)
    if identity.email:
        return identity.email.split("@", 1)[0]
    return identity.subject[:64]


@dataclass(frozen=True)
class SqlIdentityBootstrap:
    """Implements ``IdentityBootstrapPort``.

    ``default_tenant_id`` / ``default_workspace_id`` must match the seeded demo
    tenant (see ``scripts/seed_demo.py``); brand-new identities land there as
    ``default_role``.
    """

    session_factory: async_sessionmaker[AsyncSession]
    default_tenant_id: UUID
    default_workspace_id: UUID
    default_role: str = "member"
    provider: str = "oidc"

    async def bootstrap(self, identity: VerifiedIdentity) -> BootstrapView:
        subject = identity.subject
        issuer = identity.issuer
        async with self.session_factory() as session, session.begin():
            user_id, is_new = await self._resolve_user(session, identity)

            # Membership plane is RLS-scoped: pin the default tenant first.
            await session.execute(
                _SET_TENANT, {"tenant_id": str(self.default_tenant_id)}
            )
            if is_new:
                await self._provision_default_membership(session, user_id)

            user_row = (
                await session.execute(
                    sa.select(
                        tables.users.c.subject,
                        tables.users.c.email,
                        tables.users.c.display_name,
                    ).where(tables.users.c.id == user_id)
                )
            ).one()

            memberships = await self._read_memberships(session, user_id)

        return BootstrapView(
            principal_id=user_id,
            subject=user_row.subject,
            email=user_row.email,
            display_name=user_row.display_name,
            memberships=memberships,
        )

    async def _resolve_user(
        self, session: AsyncSession, identity: VerifiedIdentity
    ) -> tuple[UUID, bool]:
        """Return (user_id, is_new). Ensures the external-identity mapping."""
        mapped = (
            await session.execute(
                sa.select(tables.external_identities.c.user_id).where(
                    tables.external_identities.c.issuer == identity.issuer,
                    tables.external_identities.c.subject == identity.subject,
                )
            )
        ).first()
        if mapped is not None:
            return mapped.user_id, False

        existing = (
            await session.execute(
                sa.select(tables.users.c.id).where(
                    tables.users.c.subject == identity.subject
                )
            )
        ).first()
        is_new = existing is None
        if existing is not None:
            user_id = existing.id
        else:
            await session.execute(
                pg_insert(tables.users)
                .values(
                    id=uuid4(),
                    subject=identity.subject,
                    email=identity.email,
                    display_name=_display_name_for(identity),
                )
                .on_conflict_do_nothing(index_elements=["subject"])
            )
            # Read the id back (handles a concurrent insert winning the race).
            user_id = (
                await session.execute(
                    sa.select(tables.users.c.id).where(
                        tables.users.c.subject == identity.subject
                    )
                )
            ).scalar_one()

        await session.execute(
            pg_insert(tables.external_identities)
            .values(
                id=uuid4(),
                user_id=user_id,
                issuer=identity.issuer,
                subject=identity.subject,
                provider=self.provider,
            )
            .on_conflict_do_nothing(
                constraint="uq_external_identities_issuer_subject"
            )
        )
        return user_id, is_new

    async def _provision_default_membership(
        self, session: AsyncSession, user_id: UUID
    ) -> None:
        tenant_exists = (
            await session.execute(
                sa.select(tables.tenants.c.id).where(
                    tables.tenants.c.id == self.default_tenant_id
                )
            )
        ).first()
        if tenant_exists is None:
            # Unseeded database: user is created but has no workspace yet.
            return
        await session.execute(
            pg_insert(tables.memberships)
            .values(
                id=uuid4(),
                tenant_id=self.default_tenant_id,
                workspace_id=self.default_workspace_id,
                user_id=user_id,
                role_keys=[self.default_role],
                department="general",
            )
            .on_conflict_do_nothing(constraint="uq_memberships_scope_user")
        )

    async def _read_memberships(
        self, session: AsyncSession, user_id: UUID
    ) -> tuple[WorkspaceMembershipView, ...]:
        rows = (
            await session.execute(
                sa.select(
                    tables.memberships.c.workspace_id,
                    tables.memberships.c.role_keys,
                    tables.workspaces.c.slug.label("workspace_slug"),
                    tables.workspaces.c.name.label("workspace_name"),
                    tables.tenants.c.id.label("tenant_id"),
                    tables.tenants.c.slug.label("tenant_slug"),
                    tables.tenants.c.name.label("tenant_name"),
                )
                .select_from(
                    tables.memberships.join(
                        tables.workspaces,
                        tables.memberships.c.workspace_id == tables.workspaces.c.id,
                    ).join(
                        tables.tenants,
                        tables.memberships.c.tenant_id == tables.tenants.c.id,
                    )
                )
                .where(tables.memberships.c.user_id == user_id)
            )
        ).all()
        if not rows:
            return ()

        role_keys: set[str] = set()
        for row in rows:
            role_keys.update(row.role_keys)
        scope_by_role: dict[str, list[str]] = {}
        if role_keys:
            role_rows = await session.execute(
                sa.select(tables.roles.c.key, tables.roles.c.scopes).where(
                    tables.roles.c.key.in_(role_keys)
                )
            )
            for key, scopes in role_rows:
                scope_by_role[key] = list(scopes)

        views: list[WorkspaceMembershipView] = []
        for row in rows:
            scopes: set[str] = set()
            for key in row.role_keys:
                scopes.update(scope_by_role.get(key, []))
            views.append(
                WorkspaceMembershipView(
                    tenant_id=row.tenant_id,
                    tenant_slug=row.tenant_slug,
                    tenant_name=row.tenant_name,
                    workspace_id=row.workspace_id,
                    workspace_slug=row.workspace_slug,
                    workspace_name=row.workspace_name,
                    roles=tuple(sorted(row.role_keys)),
                    scopes=tuple(sorted(scopes)),
                )
            )
        return tuple(views)
