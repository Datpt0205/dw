"""Work-ops SQL repositories + UnitOfWork (tenant context via SET LOCAL)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from types import TracebackType

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_kernel.errors import ConflictError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_work_ops.adapters.persistence import tables
from dw_work_ops.application.ports import (
    ActionItemRepositoryPort,
    DecisionRepositoryPort,
    MeetingRepositoryPort,
    TranscriptRepositoryPort,
)
from dw_work_ops.domain.entities import (
    ActionItem,
    ActionStatus,
    DecisionRecord,
    MeetingSession,
    MeetingStatus,
    ResolvedAssignee,
    TranscriptArtifact,
)
from dw_work_ops.domain.value_objects.confidence import Confidence, RiskLevel
from dw_work_ops.domain.value_objects.ids import (
    ActionItemId,
    MeetingId,
    TranscriptArtifactId,
)

_SET_TENANT = text("SELECT set_config('app.tenant_id', :tenant_id, true)")


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _meeting_from_row(row: Row[tuple]) -> MeetingSession:  # type: ignore[type-arg]
    return MeetingSession(
        id=MeetingId(row.id),
        tenant_id=TenantId(row.tenant_id),
        workspace_id=WorkspaceId(row.workspace_id),
        title=row.title,
        occurred_at=row.occurred_at,
        created_by=UserId(row.created_by),
        status=MeetingStatus(row.status),
        transcript_artifact_id=(
            TranscriptArtifactId(row.transcript_artifact_id) if row.transcript_artifact_id else None
        ),
        last_run_id=row.last_run_id,
        summary=dict(row.summary) if row.summary is not None else None,
        analysis=dict(row.analysis) if row.analysis is not None else None,
        version=row.version,
    )


def _action_from_row(row: Row[tuple]) -> ActionItem:  # type: ignore[type-arg]
    assignee = None
    if row.assignee_person_id is not None:
        assignee = ResolvedAssignee(
            person_id=UserId(row.assignee_person_id),
            display_name=row.assignee_display_name or "",
            department=row.assignee_department or "general",
            confidence=Confidence(row.assignee_confidence),
        )
    return ActionItem(
        id=ActionItemId(row.id),
        tenant_id=TenantId(row.tenant_id),
        workspace_id=WorkspaceId(row.workspace_id),
        meeting_id=MeetingId(row.meeting_id),
        title=row.title,
        description=row.description,
        assignee=assignee,
        due_date=row.due_date,
        due_date_inferred=row.due_date_inferred,
        risk_level=RiskLevel(row.risk_level),
        status=ActionStatus(row.status),
        approval_reasons=list(row.approval_reasons),
        source_quote=row.source_quote,
        version=row.version,
    )


@dataclass
class SqlMeetingRepository(MeetingRepositoryPort):
    session: AsyncSession

    async def add(self, meeting: MeetingSession) -> None:
        await self.session.execute(
            sa.insert(tables.meetings).values(
                id=meeting.id.value,
                tenant_id=meeting.tenant_id.value,
                workspace_id=meeting.workspace_id.value,
                title=meeting.title,
                occurred_at=meeting.occurred_at,
                status=meeting.status.value,
                transcript_artifact_id=(
                    meeting.transcript_artifact_id.value if meeting.transcript_artifact_id else None
                ),
                summary=meeting.summary,
                analysis=meeting.analysis,
                last_run_id=meeting.last_run_id,
                created_by=meeting.created_by.value,
                version=meeting.version,
                created_at=_now(),
                updated_at=_now(),
            )
        )

    async def get(self, meeting_id: MeetingId) -> MeetingSession | None:
        row = (
            await self.session.execute(
                sa.select(tables.meetings).where(tables.meetings.c.id == meeting_id.value)
            )
        ).first()
        return _meeting_from_row(row) if row else None

    async def save(self, meeting: MeetingSession) -> None:
        result = await self.session.execute(
            sa.update(tables.meetings)
            .where(
                tables.meetings.c.id == meeting.id.value,
                tables.meetings.c.version == meeting.version - 1,
            )
            .values(
                status=meeting.status.value,
                transcript_artifact_id=(
                    meeting.transcript_artifact_id.value if meeting.transcript_artifact_id else None
                ),
                summary=meeting.summary,
                analysis=meeting.analysis,
                last_run_id=meeting.last_run_id,
                version=meeting.version,
                updated_at=_now(),
            )
        )
        assert isinstance(result, sa.CursorResult)
        if result.rowcount != 1:
            raise ConflictError(
                "meeting was modified concurrently",
                details={"meeting_id": str(meeting.id)},
            )

    async def list_recent(self, limit: int = 50) -> list[MeetingSession]:
        rows = await self.session.execute(
            sa.select(tables.meetings).order_by(tables.meetings.c.created_at.desc()).limit(limit)
        )
        return [_meeting_from_row(row) for row in rows]


@dataclass
class SqlTranscriptRepository(TranscriptRepositoryPort):
    session: AsyncSession

    async def add(self, artifact: TranscriptArtifact) -> None:
        await self.session.execute(
            sa.insert(tables.transcript_artifacts).values(
                id=artifact.id.value,
                tenant_id=artifact.tenant_id.value,
                workspace_id=artifact.workspace_id.value,
                meeting_id=artifact.meeting_id.value,
                storage_key=artifact.storage_key,
                filename=artifact.filename,
                content_hash=artifact.content_hash,
                uploaded_by=artifact.uploaded_by.value,
                created_at=_now(),
            )
        )

    async def get_for_meeting(self, meeting_id: MeetingId) -> TranscriptArtifact | None:
        row = (
            await self.session.execute(
                sa.select(tables.transcript_artifacts).where(
                    tables.transcript_artifacts.c.meeting_id == meeting_id.value
                )
            )
        ).first()
        if row is None:
            return None
        return TranscriptArtifact(
            id=TranscriptArtifactId(row.id),
            tenant_id=TenantId(row.tenant_id),
            workspace_id=WorkspaceId(row.workspace_id),
            meeting_id=MeetingId(row.meeting_id),
            storage_key=row.storage_key,
            filename=row.filename,
            content_hash=row.content_hash,
            uploaded_by=UserId(row.uploaded_by),
        )


@dataclass
class SqlDecisionRepository(DecisionRepositoryPort):
    session: AsyncSession

    async def replace_for_meeting(
        self, meeting_id: MeetingId, decisions: list[DecisionRecord]
    ) -> None:
        await self.session.execute(
            sa.delete(tables.decisions).where(tables.decisions.c.meeting_id == meeting_id.value)
        )
        for decision in decisions:
            await self.session.execute(
                sa.insert(tables.decisions).values(
                    id=decision.id,
                    tenant_id=decision.tenant_id.value,
                    workspace_id=decision.workspace_id.value,
                    meeting_id=decision.meeting_id.value,
                    statement=decision.statement,
                    decided_by_name=decision.decided_by_name,
                    evidence_quote=decision.evidence_quote,
                    created_at=_now(),
                )
            )

    async def list_for_meeting(self, meeting_id: MeetingId) -> list[DecisionRecord]:
        rows = await self.session.execute(
            sa.select(tables.decisions).where(tables.decisions.c.meeting_id == meeting_id.value)
        )
        return [
            DecisionRecord(
                id=row.id,
                tenant_id=TenantId(row.tenant_id),
                workspace_id=WorkspaceId(row.workspace_id),
                meeting_id=MeetingId(row.meeting_id),
                statement=row.statement,
                decided_by_name=row.decided_by_name,
                evidence_quote=row.evidence_quote,
            )
            for row in rows
        ]


@dataclass
class SqlActionItemRepository(ActionItemRepositoryPort):
    session: AsyncSession

    def _values(self, action: ActionItem) -> dict[str, object]:
        return {
            "title": action.title,
            "description": action.description,
            "assignee_person_id": action.assignee.person_id.value if action.assignee else None,
            "assignee_display_name": action.assignee.display_name if action.assignee else None,
            "assignee_department": action.assignee.department if action.assignee else None,
            "assignee_confidence": (action.assignee.confidence.value if action.assignee else 0.0),
            "due_date": action.due_date,
            "due_date_inferred": action.due_date_inferred,
            "risk_level": action.risk_level.value,
            "status": action.status.value,
            "approval_reasons": list(action.approval_reasons),
            "source_quote": action.source_quote,
            "version": action.version,
            "updated_at": _now(),
        }

    async def replace_for_meeting(self, meeting_id: MeetingId, actions: list[ActionItem]) -> None:
        await self.session.execute(
            sa.delete(tables.action_items).where(
                tables.action_items.c.meeting_id == meeting_id.value
            )
        )
        for action in actions:
            await self.session.execute(
                sa.insert(tables.action_items).values(
                    id=action.id.value,
                    tenant_id=action.tenant_id.value,
                    workspace_id=action.workspace_id.value,
                    meeting_id=action.meeting_id.value,
                    created_at=_now(),
                    **self._values(action),
                )
            )

    async def get(self, action_id: ActionItemId) -> ActionItem | None:
        row = (
            await self.session.execute(
                sa.select(tables.action_items).where(tables.action_items.c.id == action_id.value)
            )
        ).first()
        return _action_from_row(row) if row else None

    async def save(self, action: ActionItem) -> None:
        result = await self.session.execute(
            sa.update(tables.action_items)
            .where(
                tables.action_items.c.id == action.id.value,
                tables.action_items.c.version == action.version - 1,
            )
            .values(**self._values(action))
        )
        assert isinstance(result, sa.CursorResult)
        if result.rowcount != 1:
            raise ConflictError(
                "action item was modified concurrently",
                details={"action_id": str(action.id)},
            )

    async def list_for_meeting(self, meeting_id: MeetingId) -> list[ActionItem]:
        rows = await self.session.execute(
            sa.select(tables.action_items)
            .where(tables.action_items.c.meeting_id == meeting_id.value)
            .order_by(tables.action_items.c.created_at)
        )
        return [_action_from_row(row) for row in rows]

    async def record_external_task(
        self,
        action_id: ActionItemId,
        *,
        connector: str,
        connector_version: str,
        external_id: str,
        external_url: str | None,
    ) -> None:
        action = await self.get(action_id)
        assert action is not None
        await self.session.execute(
            sa.dialects.postgresql.insert(tables.external_tasks)
            .values(
                id=uuid.uuid4(),
                tenant_id=action.tenant_id.value,
                workspace_id=action.workspace_id.value,
                action_item_id=action_id.value,
                connector=connector,
                connector_version=connector_version,
                external_id=external_id,
                external_url=external_url,
                created_at=_now(),
            )
            .on_conflict_do_nothing(constraint="uq_external_tasks_action")
        )

    async def get_external_task(self, action_id: ActionItemId) -> dict[str, str | None] | None:
        row = (
            await self.session.execute(
                sa.select(tables.external_tasks).where(
                    tables.external_tasks.c.action_item_id == action_id.value
                )
            )
        ).first()
        if row is None:
            return None
        return {
            "connector": row.connector,
            "external_id": row.external_id,
            "external_url": row.external_url,
        }


class SqlWorkOpsUnitOfWork:
    """Implements ``WorkOpsUnitOfWork``."""

    meetings: MeetingRepositoryPort
    transcripts: TranscriptRepositoryPort
    decisions: DecisionRepositoryPort
    actions: ActionItemRepositoryPort

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], tenant_id: TenantId
    ) -> None:
        self._session_factory = session_factory
        self._tenant_id = tenant_id
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> SqlWorkOpsUnitOfWork:
        self._session = self._session_factory()
        await self._session.begin()
        await self._session.execute(_SET_TENANT, {"tenant_id": str(self._tenant_id)})
        self.meetings = SqlMeetingRepository(self._session)
        self.transcripts = SqlTranscriptRepository(self._session)
        self.decisions = SqlDecisionRepository(self._session)
        self.actions = SqlActionItemRepository(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        assert self._session is not None
        try:
            if exc_type is not None:
                await self._session.rollback()
        finally:
            await self._session.close()
            self._session = None

    async def commit(self) -> None:
        assert self._session is not None
        await self._session.commit()

    async def rollback(self) -> None:
        assert self._session is not None
        await self._session.rollback()


@dataclass(frozen=True)
class SqlWorkOpsUnitOfWorkFactory:
    session_factory: async_sessionmaker[AsyncSession]

    def __call__(self, tenant_id: TenantId) -> SqlWorkOpsUnitOfWork:
        return SqlWorkOpsUnitOfWork(self.session_factory, tenant_id)
