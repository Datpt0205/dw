"""Ports for the DW01 preparation slice (persistence + unit of work)."""

from __future__ import annotations

from datetime import datetime
from types import TracebackType
from typing import Protocol

from dw_kernel.ids import TenantId, UserId
from dw_tender.domain.preparation.entities import (
    ArtifactType,
    PreparationArtifact,
    PreparationCase,
    PreparationDocument,
)
from dw_tender.domain.preparation.notifications import IntakeNotificationJob
from dw_tender.domain.value_objects.ids import ArtifactId, PreparationCaseId


class PreparationCaseRepositoryPort(Protocol):
    async def add(self, case: PreparationCase) -> None: ...

    async def get(self, case_id: PreparationCaseId) -> PreparationCase | None: ...

    async def save(self, case: PreparationCase) -> None: ...

    async def list_due_for_closing(self, now: datetime) -> list[PreparationCase]:
        """Open cases whose bid register is past its closing moment."""
        ...

    async def list_recent(self, limit: int = 50) -> list[PreparationCase]: ...


class PreparationDocumentRepositoryPort(Protocol):
    async def add(self, document: PreparationDocument) -> None: ...

    async def list_for_case(self, case_id: PreparationCaseId) -> list[PreparationDocument]: ...


class PreparationArtifactRepositoryPort(Protocol):
    async def add(self, artifact: PreparationArtifact) -> None: ...

    async def get(self, artifact_id: ArtifactId) -> PreparationArtifact | None: ...

    async def list_for_case(self, case_id: PreparationCaseId) -> list[PreparationArtifact]: ...

    async def latest(
        self, case_id: PreparationCaseId, artifact_type: ArtifactType
    ) -> PreparationArtifact | None: ...

    async def mark_official(self, artifact_id: ArtifactId) -> None: ...


class IntakeNotificationRepositoryPort(Protocol):
    async def find_recipient_for_role(
        self, role_key: str, *, exclude: UserId | None = None
    ) -> UserId | None:
        """Holder of ``role_key``, skipping ``exclude`` (SoD: never route a
        decision to the person whose own case it is)."""
        ...

    async def enqueue(self, job: IntakeNotificationJob) -> None: ...

    async def list_for_case(self, case_id: PreparationCaseId) -> list[IntakeNotificationJob]: ...


class PreparationUnitOfWork(Protocol):
    cases: PreparationCaseRepositoryPort
    documents: PreparationDocumentRepositoryPort
    artifacts: PreparationArtifactRepositoryPort
    notifications: IntakeNotificationRepositoryPort

    async def __aenter__(self) -> PreparationUnitOfWork: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class PreparationUnitOfWorkFactory(Protocol):
    def __call__(self, tenant_id: TenantId) -> PreparationUnitOfWork: ...
