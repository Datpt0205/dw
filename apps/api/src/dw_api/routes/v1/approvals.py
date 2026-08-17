"""Approvals API: inbox + decisions (decision resumes the paused run)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from dw_api.dependencies.auth import RequireAccessContext
from dw_api.dependencies.services import RequireContainer
from dw_kernel.errors import InfrastructureError, NotFoundError


class ApprovalView(BaseModel):
    id: uuid.UUID
    approval_type: str
    reason: str
    status: str
    run_id: uuid.UUID | None
    payload: dict[str, Any]
    created_at: datetime | None
    decided_at: datetime | None


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approve: bool
    comment: str = ""
    approved_action_ids: list[str] | None = None


router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.get("", response_model=list[ApprovalView])
async def list_pending(
    context: RequireAccessContext, container: RequireContainer
) -> list[ApprovalView]:
    if container.uow_factory is None:
        raise InfrastructureError("database is not configured")
    await container.authorization.require(
        context=context, action="approvals.read", resource_type="approval_request"
    )
    async with container.uow_factory(context) as uow:
        pending = await uow.approvals.list_pending()
    return [
        ApprovalView(
            id=p.id,
            approval_type=p.approval_type,
            reason=p.reason,
            status=p.status.value,
            run_id=p.run_id,
            payload=dict(p.payload),
            created_at=p.created_at,
            decided_at=p.decided_at,
        )
        for p in pending
    ]


@router.get("/{approval_id}", response_model=ApprovalView)
async def get_approval(
    approval_id: uuid.UUID, context: RequireAccessContext, container: RequireContainer
) -> ApprovalView:
    if container.uow_factory is None:
        raise InfrastructureError("database is not configured")
    await container.authorization.require(
        context=context,
        action="approvals.read",
        resource_type="approval_request",
        resource_id=str(approval_id),
    )
    async with container.uow_factory(context) as uow:
        request = await uow.approvals.get(approval_id)
    if request is None:
        raise NotFoundError("approval request not found")
    return ApprovalView(
        id=request.id,
        approval_type=request.approval_type,
        reason=request.reason,
        status=request.status.value,
        run_id=request.run_id,
        payload=dict(request.payload),
        created_at=request.created_at,
        decided_at=request.decided_at,
    )


@router.post("/{approval_id}/decisions", response_model=ApprovalView)
async def decide(
    approval_id: uuid.UUID,
    body: DecisionRequest,
    context: RequireAccessContext,
    container: RequireContainer,
) -> ApprovalView:
    if container.approval_flow is None:
        raise InfrastructureError("approval flow is not configured")
    request = await container.approval_flow.decide(
        approval_id=approval_id,
        approve=body.approve,
        comment=body.comment,
        context=context,
        authorization=container.authorization,
        channel="web",
        approved_action_ids=body.approved_action_ids,
    )
    return ApprovalView(
        id=request.id,
        approval_type=request.approval_type,
        reason=request.reason,
        status=request.status.value,
        run_id=request.run_id,
        payload=dict(request.payload),
        created_at=request.created_at,
        decided_at=request.decided_at,
    )
