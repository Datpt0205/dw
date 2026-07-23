"""Platform application ports.

Adapters (Keycloak OIDC verifier, SQL membership store, policy engine) implement
these; handlers depend only on the protocols.
"""

from __future__ import annotations

from types import TracebackType
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from dw_platform.application.access_context import AccessContext

if TYPE_CHECKING:
    from dw_platform.domain.approval import ApprovalDecision, ApprovalRequest
    from dw_platform.domain.audit import AuditEvent
    from dw_platform.domain.outbox import OutboxEvent


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


class ApprovalRepositoryPort(Protocol):
    """Persistence for the approval aggregate (tenant-scoped via RLS)."""

    async def add(self, request: ApprovalRequest) -> None: ...

    async def get(self, request_id: UUID) -> ApprovalRequest | None: ...

    async def save(self, request: ApprovalRequest) -> None:
        """Persist state transition with optimistic concurrency on version."""
        ...

    async def add_decision(self, decision: ApprovalDecision) -> None: ...

    async def list_pending(self, limit: int = 50) -> list[ApprovalRequest]: ...


class AuditRepositoryPort(Protocol):
    """Append-only audit trail; no update/delete exists by design."""

    async def append(self, event: AuditEvent) -> None: ...

    async def list_recent(self, limit: int = 50) -> list[AuditEvent]: ...

    async def list_for_run(self, run_id: UUID, limit: int = 100) -> list[AuditEvent]: ...


class OutboxRepositoryPort(Protocol):
    """Transactional outbox written in the same transaction as aggregates."""

    async def add(self, event: OutboxEvent) -> None: ...

    async def list_unprocessed(self, limit: int = 100) -> list[OutboxEvent]: ...


class PlatformUnitOfWork(Protocol):
    """One transaction with trusted tenant context applied via SET LOCAL.

    Entering the UoW binds the RLS context from the AccessContext it was
    created for; every statement inside runs under that tenant.
    """

    approvals: ApprovalRepositoryPort
    audit: AuditRepositoryPort
    outbox: OutboxRepositoryPort

    async def __aenter__(self) -> PlatformUnitOfWork: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class PlatformUnitOfWorkFactory(Protocol):
    """Creates a UoW bound to a verified AccessContext."""

    def __call__(self, context: AccessContext) -> PlatformUnitOfWork: ...
