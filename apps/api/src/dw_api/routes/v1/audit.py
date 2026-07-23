"""Audit events API (read-only; audit is append-only by construction)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from dw_api.dependencies.auth import RequireAccessContext
from dw_api.dependencies.services import RequireContainer
from dw_kernel.errors import InfrastructureError


class AuditEventView(BaseModel):
    action: str
    resource_type: str
    resource_id: str
    policy_decision: str | None
    trace_id: str | None
    occurred_at: datetime
    details: dict[str, Any]


router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/events", response_model=list[AuditEventView])
async def list_events(
    context: RequireAccessContext,
    container: RequireContainer,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[AuditEventView]:
    if container.uow_factory is None:
        raise InfrastructureError("database is not configured")
    await container.authorization.require(
        context=context, action="approvals.read", resource_type="audit_event"
    )
    async with container.uow_factory(context) as uow:
        events = await uow.audit.list_recent(limit=limit)
    return [
        AuditEventView(
            action=e.action,
            resource_type=e.resource_type,
            resource_id=e.resource_id,
            policy_decision=e.policy_decision,
            trace_id=e.trace_id,
            occurred_at=e.occurred_at,
            details=dict(e.details),
        )
        for e in events
    ]
