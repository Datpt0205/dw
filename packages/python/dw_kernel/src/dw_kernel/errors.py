"""Error taxonomy shared by every layer.

Presentation layers map these onto the unified API error schema; adapters wrap
provider failures into :class:`InfrastructureError` with context instead of
letting raw SDK exceptions cross the boundary.
"""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    """Stable machine-readable error codes (part of the public contract)."""

    VALIDATION_FAILED = "validation_failed"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    PERMISSION_DENIED = "permission_denied"
    ENTITLEMENT_DENIED = "entitlement_denied"
    APPROVAL_REQUIRED = "approval_required"
    TENANT_CONTEXT_MISSING = "tenant_context_missing"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    INTERNAL = "internal"


class DWError(Exception):
    """Base error carrying a stable code and safe-to-log message."""

    code: ErrorCode = ErrorCode.INTERNAL

    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, object] = details or {}


class DomainError(DWError):
    """An invariant or business rule was violated."""

    code = ErrorCode.VALIDATION_FAILED


class NotFoundError(DWError):
    code = ErrorCode.NOT_FOUND


class ConflictError(DWError):
    code = ErrorCode.CONFLICT


class PermissionDeniedError(DWError):
    code = ErrorCode.PERMISSION_DENIED


class EntitlementDeniedError(DWError):
    """The tenant's plan does not include the requested capability."""

    code = ErrorCode.ENTITLEMENT_DENIED


class ApprovalRequiredError(DWError):
    """The action is valid but requires human approval before execution."""

    code = ErrorCode.APPROVAL_REQUIRED


class TenantContextMissingError(DWError):
    """A tenant-scoped operation ran without a verified tenant context."""

    code = ErrorCode.TENANT_CONTEXT_MISSING


class IdempotencyConflictError(DWError):
    """The same idempotency key was used with a different payload."""

    code = ErrorCode.IDEMPOTENCY_CONFLICT


class InfrastructureError(DWError):
    """A downstream dependency failed; carries taxonomy, never raw SDK errors."""

    code = ErrorCode.UPSTREAM_UNAVAILABLE
