"""Ports for the DW01 preparation slice (persistence + unit of work)."""

from __future__ import annotations

import uuid
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
from dw_tender.domain.preparation.rework import ExplanationRecord, ReworkEvent
from dw_tender.domain.value_objects.ids import ArtifactId, PreparationCaseId


class PreparationCaseRepositoryPort(Protocol):
    async def add(self, case: PreparationCase) -> None: ...

    async def get(self, case_id: PreparationCaseId) -> PreparationCase | None: ...

    async def save(self, case: PreparationCase) -> None: ...

    async def list_due_for_closing(self, now: datetime) -> list[PreparationCase]:
        """Open cases whose bid register is past its closing moment."""
        ...

    async def list_pending_law_review(self, limit: int = 20) -> list[PreparationCase]:
        """Cases whose legal basis is settled but whose outcome is not yet.

        Between those two points the package is quotable and changeable: a
        deadline has been derived from an article, and nobody has acted on the
        result. That is the only window where re-reading the law can still
        change what happens.
        """
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


class ReworkEventRepositoryPort(Protocol):
    """Returned cases — append-only, plus a way to mark a mis-click."""

    async def add(self, event: ReworkEvent) -> None: ...

    async def get(self, event_id: uuid.UUID) -> ReworkEvent | None: ...

    async def list_for_creator(self, creator_id: UserId, *, since: datetime) -> list[ReworkEvent]:
        """This person's returned cases from ``since`` onwards.

        Takes a moment, not a number of days: slicing into windows belongs to
        the pure core, so the caller passes the earliest moment any window
        needs and lets ``assess_rework`` cut it up. Tenant and workspace are
        deliberately absent from the signature — they come from the verified
        context the unit of work already set, and RLS enforces them.
        """
        ...

    async def void(
        self, event_id: uuid.UUID, *, voided_by: UserId, reason: str, at: datetime
    ) -> None:
        """Mark a mis-click. The row stays; the tally moves on without it."""
        ...


class ExplanationRepositoryPort(Protocol):
    async def add(self, record: ExplanationRecord) -> None: ...

    async def get(self, explanation_id: uuid.UUID) -> ExplanationRecord | None: ...

    async def save(self, record: ExplanationRecord) -> None:
        """Persist a decision. Only the decision columns are writable."""
        ...

    async def latest_pending_for_creator(self, creator_id: UserId) -> ExplanationRecord | None: ...

    async def has_approved_since(self, creator_id: UserId, *, since: datetime) -> bool:
        """Has this person been unblocked since ``since``?

        What lifts a block: the tally alone never does, because old events
        ageing out of the window would silently release someone the moment a
        counter ticked over rather than when a person decided it.
        """
        ...

    async def list_pending(self, *, limit: int = 50) -> list[ExplanationRecord]:
        """Everything waiting on a decision, oldest first.

        Oldest first because the person at the front of this queue is the one
        who has been unable to file for longest.
        """
        ...

    async def list_pending_overdue(self, *, before: datetime) -> list[ExplanationRecord]:
        """Explanations still waiting past the escalation deadline."""
        ...


class PreparationUnitOfWork(Protocol):
    cases: PreparationCaseRepositoryPort
    documents: PreparationDocumentRepositoryPort
    artifacts: PreparationArtifactRepositoryPort
    notifications: IntakeNotificationRepositoryPort
    rework_events: ReworkEventRepositoryPort
    explanations: ExplanationRepositoryPort

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
