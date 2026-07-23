"""GET /api/v1/me — the caller's verified access context (safe fields only)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel

from dw_api.dependencies.auth import RequireAccessContext


class MeResponse(BaseModel):
    tenant_id: UUID
    workspace_id: UUID
    principal_id: UUID
    roles: list[str]
    scopes: list[str]
    clearance: str
    plan_id: str
    feature_flags: list[str]


router = APIRouter(tags=["identity"])


@router.get("/me", response_model=MeResponse)
async def me(context: RequireAccessContext) -> MeResponse:
    return MeResponse(
        tenant_id=context.tenant_id,
        workspace_id=context.workspace_id,
        principal_id=context.principal_id,
        roles=sorted(context.roles),
        scopes=sorted(context.scopes),
        clearance=context.clearance,
        plan_id=context.plan_id,
        feature_flags=sorted(context.feature_flags),
    )
