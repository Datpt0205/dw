"""Identity bootstrap: verified token -> platform user + workspace memberships.

Used by ``GET /api/v1/auth/bootstrap`` before a workspace is selected. Unlike
``AccessContext`` building (which needs a tenant/workspace), bootstrap answers
"who am I and which workspaces can I enter?".

First-login provisioning (ADR-019): a brand-new verified identity — e.g. a user
who just self-registered in Keycloak — is added to the default demo tenant as a
plain ``member``. Existing/seeded users keep whatever memberships they already
have; they are never re-provisioned.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from dw_platform.application.ports import VerifiedIdentity


@dataclass(frozen=True, slots=True)
class WorkspaceMembershipView:
    """One workspace the caller may enter, with resolved roles/scopes."""

    tenant_id: UUID
    tenant_slug: str
    tenant_name: str
    workspace_id: UUID
    workspace_slug: str
    workspace_name: str
    roles: tuple[str, ...]
    scopes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BootstrapView:
    """The identity-only view returned by /auth/bootstrap."""

    principal_id: UUID
    subject: str
    email: str | None
    display_name: str
    memberships: tuple[WorkspaceMembershipView, ...]


class IdentityBootstrapPort(Protocol):
    """Resolves (and, for new identities, provisions) the caller's memberships."""

    async def bootstrap(self, identity: VerifiedIdentity) -> BootstrapView: ...
