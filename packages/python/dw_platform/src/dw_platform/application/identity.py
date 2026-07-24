"""Building the trusted AccessContext from verified identity + membership.

The client may REQUEST a tenant/workspace, but access is granted only when the
database confirms membership (blueprint §15.2). Nothing client-supplied is
trusted directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from dw_kernel.errors import PermissionDeniedError, TenantContextMissingError
from dw_platform.application.access_context import AccessContext
from dw_platform.application.ports import VerifiedIdentity


@dataclass(frozen=True, slots=True)
class VerifiedClaims:
    """Concrete VerifiedIdentity produced by token verifier adapters."""

    subject: str
    email: str | None
    issuer: str
    name: str | None = None


@dataclass(frozen=True, slots=True)
class MembershipAccess:
    """Resolved membership snapshot returned by the lookup port."""

    tenant_id: UUID
    workspace_id: UUID
    principal_id: UUID
    roles: frozenset[str]
    scopes: frozenset[str]
    groups: frozenset[str]
    clearance: str
    plan_id: str
    feature_flags: frozenset[str]


class MembershipLookupPort(Protocol):
    """Confirms (subject, tenant, workspace) membership against the database."""

    async def find_access(
        self,
        subject: str,
        issuer: str,
        tenant_id: UUID,
        workspace_id: UUID,
    ) -> MembershipAccess | None: ...


@dataclass(frozen=True)
class DbAccessContextFactory:
    """Implements ``AccessContextFactoryPort`` on top of the membership lookup."""

    membership_lookup: MembershipLookupPort

    async def build(
        self,
        identity: VerifiedIdentity,
        requested_tenant_id: UUID | None,
        requested_workspace_id: UUID | None,
    ) -> AccessContext:
        if requested_tenant_id is None or requested_workspace_id is None:
            raise TenantContextMissingError("X-Tenant-Id and X-Workspace-Id headers are required")
        access = await self.membership_lookup.find_access(
            subject=identity.subject,
            issuer=identity.issuer,
            tenant_id=requested_tenant_id,
            workspace_id=requested_workspace_id,
        )
        if access is None:
            # Same response for "tenant does not exist" and "not a member":
            # do not leak tenant existence to non-members.
            raise PermissionDeniedError(
                "no membership for the requested tenant/workspace",
                details={"tenant_id": str(requested_tenant_id)},
            )
        return AccessContext(
            tenant_id=access.tenant_id,
            workspace_id=access.workspace_id,
            principal_id=access.principal_id,
            roles=access.roles,
            groups=access.groups,
            scopes=access.scopes,
            clearance=access.clearance,
            plan_id=access.plan_id,
            feature_flags=access.feature_flags,
        )
