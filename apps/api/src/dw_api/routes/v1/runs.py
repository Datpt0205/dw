"""Run status + timeline API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from dw_api.dependencies.auth import RequireAccessContext
from dw_api.dependencies.services import RequireContainer
from dw_kernel.errors import InfrastructureError


class RunView(BaseModel):
    id: uuid.UUID
    status: str
    worker_id: str
    worker_version: str
    graph_version: str
    result: dict[str, Any] | None
    error: dict[str, Any] | None
    approval_request_id: uuid.UUID | None
    release_manifest_ref: str | None


class TimelineEvent(BaseModel):
    action: str
    resource_type: str
    resource_id: str
    policy_decision: str | None
    occurred_at: datetime
    details: dict[str, Any]


router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("/{run_id}", response_model=RunView)
async def get_run(
    run_id: uuid.UUID, context: RequireAccessContext, container: RequireContainer
) -> RunView:
    if container.run_store is None:
        raise InfrastructureError("runtime is not configured")
    record = await container.run_store.get(container.run_context_for(context, run_id), run_id)
    return RunView(
        id=record.id,
        status=record.status.value,
        worker_id=record.worker_id,
        worker_version=record.worker_version,
        graph_version=record.graph_version,
        result=record.result,
        error=record.error,
        approval_request_id=record.approval_request_id,
        release_manifest_ref=record.release_manifest_ref,
    )


@router.get("/{run_id}/timeline", response_model=list[TimelineEvent])
async def get_timeline(
    run_id: uuid.UUID, context: RequireAccessContext, container: RequireContainer
) -> list[TimelineEvent]:
    if container.uow_factory is None:
        raise InfrastructureError("database is not configured")
    await container.authorization.require(
        context=context,
        action="work_ops.read",
        resource_type="worker_run",
        resource_id=str(run_id),
    )
    async with container.uow_factory(context) as uow:
        events = await uow.audit.list_for_run(run_id)
    return [
        TimelineEvent(
            action=e.action,
            resource_type=e.resource_type,
            resource_id=e.resource_id,
            policy_decision=e.policy_decision,
            occurred_at=e.occurred_at,
            details=dict(e.details),
        )
        for e in events
    ]
