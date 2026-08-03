"""GET /api/v1/auth/bootstrap — identity-only "who am I / which workspaces?".

Called by the web app right after OIDC login, before a workspace is selected.
A brand-new verified identity is provisioned into the default demo tenant as a
plain member (ADR-021); existing users keep their memberships.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from dw_api.bootstrap import ApiContainer
from dw_api.dependencies.auth import RequireVerifiedIdentity, get_container
from dw_kernel.errors import InfrastructureError


class WorkspaceMembershipModel(BaseModel):
    tenant_id: UUID
    tenant_slug: str
    tenant_name: str
    workspace_id: UUID
    workspace_slug: str
    workspace_name: str
    roles: list[str]
    scopes: list[str]


class BootstrapResponse(BaseModel):
    principal_id: UUID
    subject: str
    email: str | None
    display_name: str
    memberships: list[WorkspaceMembershipModel]


router = APIRouter(tags=["identity"])


@router.get("/auth/bootstrap", response_model=BootstrapResponse)
async def bootstrap(
    identity: RequireVerifiedIdentity,
    container: Annotated[ApiContainer, Depends(get_container)],
) -> BootstrapResponse:
    if container.identity_bootstrap is None:
        raise InfrastructureError(
            "identity bootstrap is not configured",
            details={"hint": "set DW_API_DATABASE_URL"},
        )
    view = await container.identity_bootstrap.bootstrap(identity)
    return BootstrapResponse(
        principal_id=view.principal_id,
        subject=view.subject,
        email=view.email,
        display_name=view.display_name,
        memberships=[
            WorkspaceMembershipModel(
                tenant_id=m.tenant_id,
                tenant_slug=m.tenant_slug,
                tenant_name=m.tenant_name,
                workspace_id=m.workspace_id,
                workspace_slug=m.workspace_slug,
                workspace_name=m.workspace_name,
                roles=list(m.roles),
                scopes=list(m.scopes),
            )
            for m in view.memberships
        ],
    )
