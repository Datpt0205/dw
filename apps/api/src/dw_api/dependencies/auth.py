"""FastAPI dependency that turns a request into a trusted AccessContext.

Flow: bearer token → TokenVerifierPort → requested tenant/workspace headers →
membership confirmation in DB → AccessContext. Nothing client-supplied is
trusted without verification (blueprint §15.2).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Request

from dw_api.bootstrap import ApiContainer
from dw_kernel.errors import (
    InfrastructureError,
    PermissionDeniedError,
    TenantContextMissingError,
)
from dw_platform.application.access_context import AccessContext
from dw_platform.application.ports import VerifiedIdentity

TENANT_HEADER = "X-Tenant-Id"
WORKSPACE_HEADER = "X-Workspace-Id"


def get_container(request: Request) -> ApiContainer:
    container: ApiContainer = request.app.state.container
    return container


def _bearer_token(request: Request) -> str:
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise PermissionDeniedError("missing bearer token")
    return token.strip()


async def get_verified_identity(
    request: Request,
    container: Annotated[ApiContainer, Depends(get_container)],
) -> VerifiedIdentity:
    """Verify the bearer token only — no tenant/workspace membership required.

    Used by /auth/bootstrap, which answers "who am I and which workspaces can I
    enter?" before a workspace has been selected.
    """
    if container.token_verifier is None:
        raise InfrastructureError(
            "authentication is not configured",
            details={"hint": "set DW_API_DATABASE_URL and DW_API_DEV_SECRET (or OIDC)"},
        )
    return await container.token_verifier.verify(_bearer_token(request))


RequireVerifiedIdentity = Annotated[VerifiedIdentity, Depends(get_verified_identity)]


def _parse_uuid_header(request: Request, name: str) -> uuid.UUID | None:
    raw = request.headers.get(name)
    if raw is None:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise TenantContextMissingError(f"{name} must be a UUID") from exc


async def get_access_context(
    request: Request,
    container: Annotated[ApiContainer, Depends(get_container)],
) -> AccessContext:
    if container.token_verifier is None or container.access_context_factory is None:
        raise InfrastructureError(
            "authentication is not configured",
            details={"hint": "set DW_API_DATABASE_URL and DW_API_DEV_SECRET (or OIDC)"},
        )

    identity = await container.token_verifier.verify(_bearer_token(request))
    return await container.access_context_factory.build(
        identity,
        _parse_uuid_header(request, TENANT_HEADER),
        _parse_uuid_header(request, WORKSPACE_HEADER),
    )


RequireAccessContext = Annotated[AccessContext, Depends(get_access_context)]
