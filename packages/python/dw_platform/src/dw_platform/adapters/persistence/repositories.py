"""SQL repositories mapping platform tables <-> domain objects.

All queries run inside a UoW session that already carries the SET LOCAL tenant
context, so RLS constrains every statement here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.engine import CursorResult, Row
from sqlalchemy.ext.asyncio import AsyncSession

from dw_kernel.errors import ConflictError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_platform.adapters.persistence import tables
from dw_platform.domain.approval import (
    ApprovalDecision,
    ApprovalRequest,
    ApprovalStatus,
)
from dw_platform.domain.audit import AuditEvent
from dw_platform.domain.outbox import OutboxEvent


def _approval_from_row(row: Row[tuple]) -> ApprovalRequest:  # type: ignore[type-arg]
    return ApprovalRequest(
        id=row.id,
        tenant_id=TenantId(row.tenant_id),
        workspace_id=WorkspaceId(row.workspace_id),
        approval_type=row.approval_type,
        requested_by=UserId(row.requested_by),
        reason=row.reason,
        payload=dict(row.payload),
        run_id=row.run_id,
        status=ApprovalStatus(row.status),
        created_at=row.created_at,
        decided_at=row.decided_at,
        version=row.version,
    )


@dataclass
class SqlApprovalRepository:
    """Implements ``ApprovalRepositoryPort``."""

    session: AsyncSession

    async def add(self, request: ApprovalRequest) -> None:
        await self.session.execute(
            sa.insert(tables.approval_requests).values(
                id=request.id,
                tenant_id=request.tenant_id.value,
                workspace_id=request.workspace_id.value,
                approval_type=request.approval_type,
                requested_by=request.requested_by.value,
                reason=request.reason,
                payload=request.payload,
                run_id=request.run_id,
                status=request.status.value,
                version=request.version,
            )
        )

    async def get(self, request_id: uuid.UUID) -> ApprovalRequest | None:
        result = await self.session.execute(
            sa.select(tables.approval_requests).where(tables.approval_requests.c.id == request_id)
        )
        row = result.first()
        return _approval_from_row(row) if row else None

    async def save(self, request: ApprovalRequest) -> None:
        result = await self.session.execute(
            sa.update(tables.approval_requests)
            .where(
                tables.approval_requests.c.id == request.id,
                tables.approval_requests.c.version == request.version - 1,
            )
            .values(
                status=request.status.value,
                decided_at=request.decided_at,
                version=request.version,
            )
        )
        assert isinstance(result, CursorResult)
        if result.rowcount != 1:
            raise ConflictError(
                "approval request was modified concurrently",
                details={"request_id": str(request.id)},
            )

    async def list_pending(self, limit: int = 50) -> list[ApprovalRequest]:
        result = await self.session.execute(
            sa.select(tables.approval_requests)
            .where(tables.approval_requests.c.status == "pending")
            .order_by(tables.approval_requests.c.created_at.desc())
            .limit(limit)
        )
        return [_approval_from_row(row) for row in result]

    async def add_decision(self, decision: ApprovalDecision) -> None:
        await self.session.execute(
            sa.insert(tables.approval_decisions).values(
                id=decision.id,
                request_id=decision.request_id,
                tenant_id=decision.tenant_id.value,
                workspace_id=decision.workspace_id.value,
                decided_by=decision.decided_by.value,
                outcome=decision.outcome.value,
                comment=decision.comment,
                decided_at=decision.decided_at,
            )
        )


@dataclass
class SqlAuditRepository:
    """Implements ``AuditRepositoryPort``; append-only by grants."""

    session: AsyncSession

    async def append(self, event: AuditEvent) -> None:
        await self.session.execute(
            sa.insert(tables.audit_events).values(
                id=event.id,
                tenant_id=event.tenant_id.value,
                workspace_id=event.workspace_id.value,
                actor_id=event.actor_id.value,
                action=event.action,
                resource_type=event.resource_type,
                resource_id=event.resource_id,
                run_id=event.run_id,
                policy_decision=event.policy_decision,
                trace_id=event.trace_id,
                details=event.details,
                occurred_at=event.occurred_at,
            )
        )

    async def list_for_run(self, run_id: uuid.UUID, limit: int = 100) -> list[AuditEvent]:
        result = await self.session.execute(
            sa.select(tables.audit_events)
            .where(tables.audit_events.c.run_id == run_id)
            .order_by(tables.audit_events.c.occurred_at)
            .limit(limit)
        )
        return self._map_rows(result)

    async def list_recent(self, limit: int = 50) -> list[AuditEvent]:
        result = await self.session.execute(
            sa.select(tables.audit_events)
            .order_by(tables.audit_events.c.occurred_at.desc())
            .limit(limit)
        )
        return self._map_rows(result)

    @staticmethod
    def _map_rows(result: sa.engine.Result[tuple]) -> list[AuditEvent]:  # type: ignore[type-arg]
        return [
            AuditEvent(
                id=row.id,
                tenant_id=TenantId(row.tenant_id),
                workspace_id=WorkspaceId(row.workspace_id),
                actor_id=UserId(row.actor_id),
                action=row.action,
                resource_type=row.resource_type,
                resource_id=row.resource_id,
                run_id=row.run_id,
                policy_decision=row.policy_decision,
                trace_id=row.trace_id,
                details=dict(row.details),
                occurred_at=row.occurred_at,
            )
            for row in result
        ]


@dataclass
class SqlOutboxRepository:
    """Implements ``OutboxRepositoryPort``."""

    session: AsyncSession

    async def add(self, event: OutboxEvent) -> None:
        await self.session.execute(
            sa.insert(tables.outbox_events).values(
                id=event.id,
                tenant_id=event.tenant_id.value,
                workspace_id=event.workspace_id.value,
                event_type=event.event_type,
                schema_version=event.schema_version,
                aggregate_id=event.aggregate_id,
                payload=event.payload,
                correlation_id=event.correlation_id,
                causation_id=event.causation_id,
                actor_id=event.actor_id,
                occurred_at=event.occurred_at,
                processed_at=event.processed_at,
                attempts=event.attempts,
            )
        )

    async def list_unprocessed(self, limit: int = 100) -> list[OutboxEvent]:
        result = await self.session.execute(
            sa.select(tables.outbox_events)
            .where(tables.outbox_events.c.processed_at.is_(None))
            .order_by(tables.outbox_events.c.occurred_at)
            .limit(limit)
        )
        return [
            OutboxEvent(
                id=row.id,
                tenant_id=TenantId(row.tenant_id),
                workspace_id=WorkspaceId(row.workspace_id),
                event_type=row.event_type,
                schema_version=row.schema_version,
                aggregate_id=row.aggregate_id,
                occurred_at=row.occurred_at,
                payload=dict(row.payload),
                correlation_id=row.correlation_id,
                causation_id=row.causation_id,
                actor_id=row.actor_id,
                processed_at=row.processed_at,
                attempts=row.attempts,
            )
            for row in result
        ]
