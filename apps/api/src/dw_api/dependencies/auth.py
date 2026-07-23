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

TENANT_HEADER = "X-Tenant-Id"
WORKSPACE_HEADER = "X-Workspace-Id"


def get_container(request: Request) -> ApiContainer:
    container: ApiContainer = request.app.state.container
    return container


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

    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise PermissionDeniedError("missing bearer token")

    identity = await container.token_verifier.verify(token.strip())
    return await container.access_context_factory.build(
        identity,
        _parse_uuid_header(request, TENANT_HEADER),
        _parse_uuid_header(request, WORKSPACE_HEADER),
    )


RequireAccessContext = Annotated[AccessContext, Depends(get_access_context)]
