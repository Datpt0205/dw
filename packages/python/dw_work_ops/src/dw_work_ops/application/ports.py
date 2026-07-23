"""Work-ops application ports."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from types import TracebackType
from typing import Protocol

from dw_kernel.ids import TenantId, UserId
from dw_work_ops.domain.entities import (
    ActionItem,
    DecisionRecord,
    MeetingSession,
    TranscriptArtifact,
)
from dw_work_ops.domain.value_objects.ids import ActionItemId, MeetingId


class MeetingRepositoryPort(Protocol):
    async def add(self, meeting: MeetingSession) -> None: ...

    async def get(self, meeting_id: MeetingId) -> MeetingSession | None: ...

    async def save(self, meeting: MeetingSession) -> None: ...

    async def list_recent(self, limit: int = 50) -> list[MeetingSession]: ...


class TranscriptRepositoryPort(Protocol):
    async def add(self, artifact: TranscriptArtifact) -> None: ...

    async def get_for_meeting(self, meeting_id: MeetingId) -> TranscriptArtifact | None: ...


class DecisionRepositoryPort(Protocol):
    async def replace_for_meeting(
        self, meeting_id: MeetingId, decisions: list[DecisionRecord]
    ) -> None: ...

    async def list_for_meeting(self, meeting_id: MeetingId) -> list[DecisionRecord]: ...


class ActionItemRepositoryPort(Protocol):
    async def replace_for_meeting(
        self, meeting_id: MeetingId, actions: list[ActionItem]
    ) -> None: ...

    async def get(self, action_id: ActionItemId) -> ActionItem | None: ...

    async def save(self, action: ActionItem) -> None: ...

    async def list_for_meeting(self, meeting_id: MeetingId) -> list[ActionItem]: ...

    async def record_external_task(
        self,
        action_id: ActionItemId,
        *,
        connector: str,
        connector_version: str,
        external_id: str,
        external_url: str | None,
    ) -> None: ...

    async def get_external_task(self, action_id: ActionItemId) -> dict[str, str | None] | None: ...


class WorkOpsUnitOfWork(Protocol):
    meetings: MeetingRepositoryPort
    transcripts: TranscriptRepositoryPort
    decisions: DecisionRepositoryPort
    actions: ActionItemRepositoryPort

    async def __aenter__(self) -> WorkOpsUnitOfWork: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class WorkOpsUnitOfWorkFactory(Protocol):
    def __call__(self, tenant_id: TenantId) -> WorkOpsUnitOfWork: ...


@dataclass(frozen=True, slots=True)
class DirectoryPerson:
    """Canonical person record from the organization directory."""

    person_id: UserId
    display_name: str
    department: str
    email: str | None


class OrganizationDirectoryPort(Protocol):
    """Resolves people of ONE tenant from the system of record (never the model)."""

    async def list_people(self, tenant_id: uuid.UUID) -> list[DirectoryPerson]: ...


class TranscriptStoragePort(Protocol):
    """Artifact storage for raw transcripts."""

    async def put_object(self, key: str, data: bytes, content_type: str) -> str: ...

    async def get_object(self, key: str) -> bytes: ...
