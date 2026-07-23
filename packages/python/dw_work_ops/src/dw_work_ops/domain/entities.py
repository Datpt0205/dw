"""Work Operations domain entities (blueprint §4.3, §19.4)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_work_ops.domain.exceptions import UnresolvedAssigneeError, WorkOpsDomainError
from dw_work_ops.domain.value_objects.confidence import Confidence, RiskLevel
from dw_work_ops.domain.value_objects.ids import (
    ActionItemId,
    MeetingId,
    TranscriptArtifactId,
)


class MeetingStatus(StrEnum):
    CREATED = "created"
    PROCESSING = "processing"
    ACTIONS_READY = "actions_ready"
    COMPLETED = "completed"


class ActionStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    DISPATCHED = "dispatched"
    REJECTED = "rejected"


@dataclass(slots=True)
class MeetingSession:
    id: MeetingId
    tenant_id: TenantId
    workspace_id: WorkspaceId
    title: str
    occurred_at: datetime
    created_by: UserId
    status: MeetingStatus = MeetingStatus.CREATED
    transcript_artifact_id: TranscriptArtifactId | None = None
    last_run_id: uuid.UUID | None = None
    summary: dict[str, object] | None = None
    version: int = 1

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise WorkOpsDomainError("meeting title must not be blank")
        if self.occurred_at.tzinfo is None:
            raise WorkOpsDomainError("meeting occurred_at must be timezone-aware")

    def attach_transcript(self, artifact_id: TranscriptArtifactId) -> None:
        self.transcript_artifact_id = artifact_id
        self.version += 1

    def start_processing(self, run_id: uuid.UUID) -> None:
        if self.transcript_artifact_id is None:
            raise WorkOpsDomainError("cannot generate actions without a transcript")
        self.status = MeetingStatus.PROCESSING
        self.last_run_id = run_id
        self.version += 1

    def mark_actions_ready(self, summary: dict[str, object]) -> None:
        self.status = MeetingStatus.ACTIONS_READY
        self.summary = summary
        self.version += 1

    def complete(self) -> None:
        self.status = MeetingStatus.COMPLETED
        self.version += 1


@dataclass(frozen=True, slots=True)
class TranscriptArtifact:
    id: TranscriptArtifactId
    tenant_id: TenantId
    workspace_id: WorkspaceId
    meeting_id: MeetingId
    storage_key: str
    filename: str
    content_hash: str
    uploaded_by: UserId


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    id: uuid.UUID
    tenant_id: TenantId
    workspace_id: WorkspaceId
    meeting_id: MeetingId
    statement: str
    decided_by_name: str | None = None
    evidence_quote: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedAssignee:
    person_id: UserId
    display_name: str
    department: str
    confidence: Confidence


@dataclass(slots=True)
class ActionItem:
    id: ActionItemId
    tenant_id: TenantId
    workspace_id: WorkspaceId
    meeting_id: MeetingId
    title: str
    description: str = ""
    assignee: ResolvedAssignee | None = None
    due_date: datetime | None = None
    due_date_inferred: bool = False
    risk_level: RiskLevel = RiskLevel.LOW
    status: ActionStatus = ActionStatus.PROPOSED
    approval_reasons: list[str] = field(default_factory=list)
    source_quote: str | None = None
    version: int = 1

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise WorkOpsDomainError("action title must not be blank")

    def approve(self) -> None:
        if self.status is not ActionStatus.PROPOSED:
            raise WorkOpsDomainError(f"cannot approve action in status {self.status}")
        self.status = ActionStatus.APPROVED
        self.version += 1

    def reject(self) -> None:
        if self.status is not ActionStatus.PROPOSED:
            raise WorkOpsDomainError(f"cannot reject action in status {self.status}")
        self.status = ActionStatus.REJECTED
        self.version += 1

    def mark_dispatched(self) -> None:
        if self.status is not ActionStatus.APPROVED:
            raise WorkOpsDomainError("only approved actions can be dispatched")
        if self.assignee is None:
            raise UnresolvedAssigneeError("cannot dispatch without a resolved assignee")
        self.status = ActionStatus.DISPATCHED
        self.version += 1
