"""SQL implementation of the membership lookup used to build AccessContext.

The requested tenant becomes the RLS context for the lookup transaction itself:
if the caller is not a member, RLS + the membership predicate return no rows and
access is denied. The client-requested tenant is only ever used as a filter that
must be CONFIRMED by data, never trusted directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_platform.adapters.persistence import tables
from dw_platform.application.identity import MembershipAccess

_SET_LOOKUP_CONTEXT = text("SELECT set_config('app.tenant_id', :tenant_id, true)")


@dataclass(frozen=True)
class SqlMembershipLookup:
    """Implements ``MembershipLookupPort``."""

    session_factory: async_sessionmaker[AsyncSession]

    async def find_access(
        self,
        subject: str,
        issuer: str,
        tenant_id: UUID,
        workspace_id: UUID,
    ) -> MembershipAccess | None:
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_LOOKUP_CONTEXT, {"tenant_id": str(tenant_id)})

            # The verified identity resolves to a platform user either directly
            # (dev tokens store the subject on users.subject) or via an external
            # identity mapping (Keycloak sub -> platform user).
            candidate_users = (
                sa.select(tables.users.c.id)
                .where(tables.users.c.subject == subject)
                .union(
                    sa.select(tables.external_identities.c.user_id).where(
                        tables.external_identities.c.issuer == issuer,
                        tables.external_identities.c.subject == subject,
                    )
                )
            )

            membership_row = (
                await session.execute(
                    sa.select(
                        tables.memberships.c.user_id,
                        tables.memberships.c.role_keys,
                        tables.memberships.c.clearance,
                    ).where(
                        tables.memberships.c.user_id.in_(candidate_users),
                        tables.memberships.c.tenant_id == tenant_id,
                        tables.memberships.c.workspace_id == workspace_id,
                    )
                )
            ).first()
            if membership_row is None:
                return None

            role_keys = frozenset(membership_row.role_keys)
            scopes: set[str] = set()
            if role_keys:
                roles_result = await session.execute(
                    sa.select(tables.roles.c.scopes).where(tables.roles.c.key.in_(role_keys))
                )
                for (role_scopes,) in roles_result:
                    scopes.update(role_scopes)

            entitlement_row = (
                await session.execute(
                    sa.select(
                        tables.entitlements.c.plan_id,
                        tables.entitlements.c.feature_overrides,
                        tables.plans.c.features,
                    )
                    .select_from(
                        tables.entitlements.join(
                            tables.plans,
                            tables.entitlements.c.plan_id == tables.plans.c.plan_id,
                        )
                    )
                    .where(tables.entitlements.c.tenant_id == tenant_id)
                )
            ).first()
            if entitlement_row is None:
                return None  # tenant without a plan: fail closed

            feature_flags = frozenset(entitlement_row.features) | frozenset(
                entitlement_row.feature_overrides
            )
            return MembershipAccess(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                principal_id=membership_row.user_id,
                roles=role_keys,
                scopes=frozenset(scopes),
                groups=frozenset(),
                clearance=membership_row.clearance,
                plan_id=entitlement_row.plan_id,
                feature_flags=feature_flags,
            )
