"""SQL persistence for DW01 rework support (RLS-scoped per transaction).

Kept out of ``repositories.py`` so that file stops growing, and because these
two carry a rule the others do not: they are append-only. There is no generic
``save`` here on purpose. The runtime role's grants allow UPDATE on the void
columns and the decision columns and nothing else, so a well-meaning update
helper would not fail in review — it would fail in production, at the moment
somebody needed it to work.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_tender.adapters.preparation import tables
from dw_tender.domain.preparation.rework import (
    ExplanationKind,
    ExplanationRecord,
    ExplanationStatus,
    ReworkCheckpoint,
    ReworkEvent,
)
from dw_tender.domain.value_objects.ids import PreparationCaseId


def _event_from_row(row: sa.Row[Any]) -> ReworkEvent:
    return ReworkEvent(
        id=row.id,
        tenant_id=TenantId(row.tenant_id),
        workspace_id=WorkspaceId(row.workspace_id),
        case_id=PreparationCaseId(row.case_id),
        creator_user_id=UserId(row.creator_user_id),
        decided_by_user_id=UserId(row.decided_by_user_id),
        checkpoint=ReworkCheckpoint(row.checkpoint),
        reason_code=row.reason_code,
        reason_text=row.reason_text,
        policy_version=row.policy_version,
        occurred_at=row.occurred_at,
        voided_at=row.voided_at,
        voided_by=UserId(row.voided_by) if row.voided_by is not None else None,
        void_reason=row.void_reason,
    )


def _explanation_from_row(row: sa.Row[Any]) -> ExplanationRecord:
    return ExplanationRecord(
        id=row.id,
        tenant_id=TenantId(row.tenant_id),
        workspace_id=WorkspaceId(row.workspace_id),
        case_id=PreparationCaseId(row.case_id) if row.case_id is not None else None,
        creator_user_id=UserId(row.creator_user_id),
        context_text=row.context_text,
        difficulty_text=row.difficulty_text,
        support_request_text=row.support_request_text,
        counted_event_ids=tuple(uuid.UUID(str(x)) for x in (row.counted_event_ids or [])),
        nudge_count=row.nudge_count,
        block_count=row.block_count,
        top_reason_code=row.top_reason_code,
        kind=ExplanationKind(row.kind),
        policy_version=row.policy_version,
        status=ExplanationStatus(row.status),
        decided_by=UserId(row.decided_by) if row.decided_by is not None else None,
        decided_at=row.decided_at,
        decision_comment=row.decision_comment,
        submitted_at=row.submitted_at,
    )


@dataclass
class SqlReworkEventRepository:
    session: AsyncSession

    async def add(self, event: ReworkEvent) -> None:
        await self.session.execute(
            sa.insert(tables.preparation_rework_events).values(
                id=event.id,
                tenant_id=event.tenant_id.value,
                workspace_id=event.workspace_id.value,
                case_id=event.case_id.value,
                creator_user_id=event.creator_user_id.value,
                decided_by_user_id=event.decided_by_user_id.value,
                checkpoint=event.checkpoint.value,
                reason_code=event.reason_code,
                reason_text=event.reason_text,
                policy_version=event.policy_version,
                occurred_at=event.occurred_at,
            )
        )

    async def get(self, event_id: uuid.UUID) -> ReworkEvent | None:
        result = await self.session.execute(
            sa.select(tables.preparation_rework_events).where(
                tables.preparation_rework_events.c.id == event_id
            )
        )
        row = result.first()
        return _event_from_row(row) if row is not None else None

    async def list_for_creator(self, creator_id: UserId, *, since: datetime) -> list[ReworkEvent]:
        """Everything from ``since`` onwards, voided rows included.

        Voided rows come back deliberately. Filtering them in SQL would make
        the pure core's exclusion rule untestable without a database, and
        would hide from the caller that a correction happened at all.
        """
        result = await self.session.execute(
            sa.select(tables.preparation_rework_events)
            .where(
                tables.preparation_rework_events.c.creator_user_id == creator_id.value,
                tables.preparation_rework_events.c.occurred_at >= since,
            )
            .order_by(tables.preparation_rework_events.c.occurred_at.desc())
        )
        return [_event_from_row(row) for row in result]

    async def void(
        self, event_id: uuid.UUID, *, voided_by: UserId, reason: str, at: datetime
    ) -> None:
        """Mark a mis-click — the only UPDATE this table's grants permit.

        Idempotent by design: the WHERE clause refuses to overwrite an
        existing void, so a double click cannot rewrite who corrected what.
        """
        await self.session.execute(
            sa.update(tables.preparation_rework_events)
            .where(
                tables.preparation_rework_events.c.id == event_id,
                tables.preparation_rework_events.c.voided_at.is_(None),
            )
            .values(voided_at=at, voided_by=voided_by.value, void_reason=reason)
        )


@dataclass
class SqlExplanationRepository:
    session: AsyncSession

    async def add(self, record: ExplanationRecord) -> None:
        await self.session.execute(
            sa.insert(tables.preparation_explanations).values(
                id=record.id,
                tenant_id=record.tenant_id.value,
                workspace_id=record.workspace_id.value,
                case_id=record.case_id.value if record.case_id is not None else None,
                creator_user_id=record.creator_user_id.value,
                kind=record.kind.value,
                context_text=record.context_text,
                difficulty_text=record.difficulty_text,
                support_request_text=record.support_request_text,
                counted_event_ids=[str(x) for x in record.counted_event_ids],
                nudge_count=record.nudge_count,
                block_count=record.block_count,
                top_reason_code=record.top_reason_code,
                policy_version=record.policy_version,
                status=record.status.value,
                submitted_at=record.submitted_at,
            )
        )

    async def get(self, explanation_id: uuid.UUID) -> ExplanationRecord | None:
        result = await self.session.execute(
            sa.select(tables.preparation_explanations).where(
                tables.preparation_explanations.c.id == explanation_id
            )
        )
        row = result.first()
        return _explanation_from_row(row) if row is not None else None

    async def save(self, record: ExplanationRecord) -> None:
        """Write back the decision, and only the decision.

        The WHERE clause pins ``status = 'pending'``: the aggregate already
        refuses a second decision, and this makes two concurrent approvals
        resolve to one write rather than to whichever transaction commits last.
        """
        await self.session.execute(
            sa.update(tables.preparation_explanations)
            .where(
                tables.preparation_explanations.c.id == record.id,
                tables.preparation_explanations.c.status == ExplanationStatus.PENDING.value,
            )
            .values(
                status=record.status.value,
                decided_by=record.decided_by.value if record.decided_by is not None else None,
                decided_at=record.decided_at,
                decision_comment=record.decision_comment,
            )
        )

    async def latest_pending_for_creator(
        self, creator_id: UserId, *, kind: str = "rework"
    ) -> ExplanationRecord | None:
        result = await self.session.execute(
            sa.select(tables.preparation_explanations)
            .where(
                tables.preparation_explanations.c.creator_user_id == creator_id.value,
                tables.preparation_explanations.c.status == ExplanationStatus.PENDING.value,
                tables.preparation_explanations.c.kind == kind,
            )
            .order_by(tables.preparation_explanations.c.submitted_at.desc())
            .limit(1)
        )
        row = result.first()
        return _explanation_from_row(row) if row is not None else None

    async def has_approved_since(
        self, creator_id: UserId, *, since: datetime, kind: str = "rework"
    ) -> bool:
        result = await self.session.execute(
            sa.select(sa.literal(1))
            .select_from(tables.preparation_explanations)
            .where(
                tables.preparation_explanations.c.creator_user_id == creator_id.value,
                tables.preparation_explanations.c.status == ExplanationStatus.APPROVED.value,
                tables.preparation_explanations.c.kind == kind,
                tables.preparation_explanations.c.decided_at >= since,
            )
            .limit(1)
        )
        return result.first() is not None

    async def list_pending(self, *, limit: int = 50) -> list[ExplanationRecord]:
        result = await self.session.execute(
            sa.select(tables.preparation_explanations)
            .where(tables.preparation_explanations.c.status == ExplanationStatus.PENDING.value)
            .order_by(tables.preparation_explanations.c.submitted_at.asc())
            .limit(limit)
        )
        return [_explanation_from_row(row) for row in result]

    async def list_pending_overdue(self, *, before: datetime) -> list[ExplanationRecord]:
        result = await self.session.execute(
            sa.select(tables.preparation_explanations)
            .where(
                tables.preparation_explanations.c.status == ExplanationStatus.PENDING.value,
                tables.preparation_explanations.c.submitted_at <= before,
            )
            .order_by(tables.preparation_explanations.c.submitted_at.asc())
        )
        return [_explanation_from_row(row) for row in result]
