"""Work-ops application command/query handlers.

Handlers own authorization, entitlement, transactions and orchestration; API
routes stay thin and workflow nodes call the same services (blueprint §7.5).
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime

from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.ports import WorkflowRunnerPort
from dw_kernel.errors import DomainError, NotFoundError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.ports import IdGenerator, UtcClock
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.entitlement import PlanEntitlementService
from dw_work_ops.application.dto import ActionItemView, MeetingView
from dw_work_ops.application.ports import (
    TranscriptStoragePort,
    WorkOpsUnitOfWorkFactory,
)
from dw_work_ops.domain.entities import (
    MeetingSession,
    TranscriptArtifact,
)
from dw_work_ops.domain.value_objects.ids import MeetingId, TranscriptArtifactId

WORK_OPS_FEATURE = "work_ops_worker"


@dataclass(frozen=True)
class CreateMeetingCommand:
    title: str
    occurred_at: datetime
    transcript_text: str
    transcript_filename: str


@dataclass
class CreateMeetingHandler:
    uow_factory: WorkOpsUnitOfWorkFactory
    storage: TranscriptStoragePort
    authorization: ScopeAuthorizationService
    entitlement: PlanEntitlementService
    clock: UtcClock
    id_generator: IdGenerator

    async def handle(self, cmd: CreateMeetingCommand, context: AccessContext) -> uuid.UUID:
        await self.authorization.require(
            context=context, action="work_ops.write", resource_type="meeting"
        )
        await self.entitlement.require_feature(context, WORK_OPS_FEATURE)
        if not cmd.transcript_text.strip():
            raise DomainError("transcript must not be empty")

        meeting_id = MeetingId(self.id_generator.new_uuid())
        artifact_id = TranscriptArtifactId(self.id_generator.new_uuid())
        content = cmd.transcript_text.encode("utf-8")
        storage_key = f"{context.tenant_id}/{context.workspace_id}/transcripts/{artifact_id}"
        await self.storage.put_object(storage_key, content, "text/plain; charset=utf-8")

        meeting = MeetingSession(
            id=meeting_id,
            tenant_id=TenantId(context.tenant_id),
            workspace_id=WorkspaceId(context.workspace_id),
            title=cmd.title,
            occurred_at=cmd.occurred_at,
            created_by=UserId(context.principal_id),
        )
        artifact = TranscriptArtifact(
            id=artifact_id,
            tenant_id=TenantId(context.tenant_id),
            workspace_id=WorkspaceId(context.workspace_id),
            meeting_id=meeting_id,
            storage_key=storage_key,
            filename=cmd.transcript_filename,
            content_hash=hashlib.sha256(content).hexdigest(),
            uploaded_by=UserId(context.principal_id),
        )
        meeting.attach_transcript(artifact_id)

        async with self.uow_factory(TenantId(context.tenant_id)) as uow:
            await uow.meetings.add(meeting)
            await uow.transcripts.add(artifact)
            await uow.commit()
        return meeting_id.value


@dataclass
class GetMeetingHandler:
    uow_factory: WorkOpsUnitOfWorkFactory
    authorization: ScopeAuthorizationService

    async def handle(self, meeting_id: uuid.UUID, context: AccessContext) -> MeetingView:
        await self.authorization.require(
            context=context,
            action="work_ops.read",
            resource_type="meeting",
            resource_id=str(meeting_id),
        )
        async with self.uow_factory(TenantId(context.tenant_id)) as uow:
            meeting = await uow.meetings.get(MeetingId(meeting_id))
            if meeting is None:
                raise NotFoundError("meeting not found", details={"meeting_id": str(meeting_id)})
            decisions = await uow.decisions.list_for_meeting(meeting.id)
            actions = await uow.actions.list_for_meeting(meeting.id)
            views: list[ActionItemView] = []
            for action in actions:
                external = await uow.actions.get_external_task(action.id)
                views.append(ActionItemView.from_domain(action, external))
        return MeetingView.from_domain(meeting, decisions, views)


@dataclass
class ListMeetingsHandler:
    uow_factory: WorkOpsUnitOfWorkFactory
    authorization: ScopeAuthorizationService

    async def handle(self, context: AccessContext) -> list[MeetingView]:
        await self.authorization.require(
            context=context, action="work_ops.read", resource_type="meeting"
        )
        async with self.uow_factory(TenantId(context.tenant_id)) as uow:
            meetings = await uow.meetings.list_recent()
        return [MeetingView.from_domain(m, [], []) for m in meetings]


@dataclass
class GenerateActionsHandler:
    """Starts the WorkOps agent run for a meeting (blueprint §7.5 example)."""

    uow_factory: WorkOpsUnitOfWorkFactory
    workflow_runner: WorkflowRunnerPort
    authorization: ScopeAuthorizationService
    entitlement: PlanEntitlementService
    id_generator: IdGenerator
    worker_id: str = "work_ops"
    worker_version: str = "1.1.0"

    async def handle(self, meeting_id: uuid.UUID, context: AccessContext) -> uuid.UUID:
        await self.authorization.require(
            context=context,
            action="work_ops.write",
            resource_type="meeting",
            resource_id=str(meeting_id),
        )
        await self.entitlement.require_feature(context, WORK_OPS_FEATURE)

        run_id = self.id_generator.new_uuid()
        async with self.uow_factory(TenantId(context.tenant_id)) as uow:
            meeting = await uow.meetings.get(MeetingId(meeting_id))
            if meeting is None:
                raise NotFoundError("meeting not found", details={"meeting_id": str(meeting_id)})
            meeting.start_processing(run_id)
            await uow.meetings.save(meeting)
            await uow.commit()

        run_context = RunContext(
            run_id=run_id,
            tenant_id=context.tenant_id,
            workspace_id=context.workspace_id,
            actor_id=context.principal_id,
            worker_id=self.worker_id,
            worker_version=self.worker_version,
            channel="web",
            plan_id=context.plan_id,
            roles=context.roles,
            scopes=context.scopes,
            trace_id=f"run-{run_id.hex[:12]}",
        )
        await self.workflow_runner.start(
            run_context=run_context, input_payload={"meeting_id": str(meeting_id)}
        )
        return run_id
