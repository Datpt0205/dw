"""Platform application ports.

Adapters (Keycloak OIDC verifier, SQL membership store, policy engine) implement
these; handlers depend only on the protocols.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from dw_platform.application.access_context import AccessContext


class VerifiedIdentity(Protocol):
    """Claims extracted from a cryptographically verified token."""

    @property
    def subject(self) -> str: ...

    @property
    def email(self) -> str | None: ...

    @property
    def issuer(self) -> str: ...


class TokenVerifierPort(Protocol):
    """Verifies a bearer token and returns trusted claims.

    Implementations: Keycloak OIDC (production/compose), local dev issuer
    (tests/dev). Raises ``PermissionDeniedError`` on any verification failure.
    """

    async def verify(self, token: str) -> VerifiedIdentity: ...


class AccessContextFactoryPort(Protocol):
    """Builds an :class:`AccessContext` from verified identity + membership.

    Never trusts a client-supplied tenant id without checking membership.
    """

    async def build(
        self,
        identity: VerifiedIdentity,
        requested_tenant_id: UUID | None,
        requested_workspace_id: UUID | None,
    ) -> AccessContext: ...


class AuthorizationPort(Protocol):
    """Decides whether a principal may perform an action on a resource.

    Distinct from entitlement (plan capability) checks by design (§15.1).
    """

    async def require(
        self,
        *,
        context: AccessContext,
        action: str,
        resource_type: str,
        resource_id: str | None = None,
    ) -> None:
        """Raise ``PermissionDeniedError`` when the action is not allowed."""
        ...


class EntitlementPort(Protocol):
    """Checks plan-level capability/quota; raises ``EntitlementDeniedError``."""

    async def require_feature(self, context: AccessContext, feature: str) -> None: ...
