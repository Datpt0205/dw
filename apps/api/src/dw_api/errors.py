"""Unified API error schema (blueprint §16.1) and DWError mapping."""

from __future__ import annotations

from pydantic import BaseModel

from dw_kernel.errors import ErrorCode

_STATUS_BY_CODE: dict[ErrorCode, int] = {
    ErrorCode.VALIDATION_FAILED: 422,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.CONFLICT: 409,
    ErrorCode.PERMISSION_DENIED: 403,
    ErrorCode.ENTITLEMENT_DENIED: 403,
    ErrorCode.APPROVAL_REQUIRED: 409,
    ErrorCode.TENANT_CONTEXT_MISSING: 401,
    ErrorCode.IDEMPOTENCY_CONFLICT: 409,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.TIMEOUT: 504,
    ErrorCode.UPSTREAM_UNAVAILABLE: 503,
    ErrorCode.INTERNAL: 500,
}


class ErrorResponse(BaseModel):
    """The single error envelope returned by every endpoint."""

    code: str
    message: str
    details: dict[str, object] = {}
    request_id: str | None = None


def status_for(code: ErrorCode) -> int:
    return _STATUS_BY_CODE.get(code, 500)
