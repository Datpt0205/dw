"""API view models for the DW01 preparation slice."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from dw_tender.domain.preparation.entities import (
    PreparationArtifact,
    PreparationCase,
    PreparationDocument,
)
from dw_tender.domain.preparation.notifications import IntakeNotificationJob


class DocumentView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    kind: str
    title: str
    filename: str
    content_type: str
    size_bytes: int
    content_hash: str

    @classmethod
    def from_domain(cls, document: PreparationDocument) -> DocumentView:
        return cls(
            id=document.id.value,
            kind=document.kind.value,
            title=document.title,
            filename=document.filename,
            content_type=document.content_type,
            size_bytes=document.size_bytes,
            content_hash=document.content_hash,
        )


class ArtifactView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    artifact_type: str
    artifact_version: int
    status: str
    content: dict[str, Any]
    content_hash: str

    @classmethod
    def from_domain(cls, artifact: PreparationArtifact) -> ArtifactView:
        return cls(
            id=artifact.id.value,
            artifact_type=artifact.artifact_type.value,
            artifact_version=artifact.artifact_version,
            status=artifact.status.value,
            content=artifact.content,
            content_hash=artifact.content_hash,
        )


class NotificationView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    event_type: str
    status: str
    attempts: int
    due_at: str
    sent_at: str | None
    last_error: str | None

    @classmethod
    def from_domain(cls, job: IntakeNotificationJob) -> NotificationView:
        return cls(
            id=job.id,
            event_type=job.event_type.value,
            status=job.status.value,
            attempts=job.attempts,
            due_at=job.due_at.isoformat(),
            sent_at=job.sent_at.isoformat() if job.sent_at is not None else None,
            last_error=job.last_error,
        )


class PreparationCaseView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    title: str
    description: str
    source_pr_ref: str
    estimated_value_minor: int
    currency: str
    deadline: str | None
    owner_name: str
    procurement_type: str
    business_domain: str
    method_key: str | None
    state: str
    current_step: str
    last_run_id: UUID | None
    export_ref: str | None
    current_official_artifact_id: UUID | None
    intake_verified_by: UUID | None
    intake_verified_at: str | None
    version: int
    documents: list[DocumentView] = []
    artifacts: list[ArtifactView] = []
    notifications: list[NotificationView] = []

    @classmethod
    def from_domain(
        cls,
        case: PreparationCase,
        artifacts: list[PreparationArtifact] | None = None,
        documents: list[PreparationDocument] | None = None,
        notifications: list[IntakeNotificationJob] | None = None,
    ) -> PreparationCaseView:
        return cls(
            id=case.id.value,
            title=case.title,
            description=case.description,
            source_pr_ref=case.source_pr_ref,
            estimated_value_minor=case.estimated_value_minor,
            currency=case.currency,
            deadline=case.deadline,
            owner_name=case.owner_name,
            procurement_type=case.procurement_type.value,
            business_domain=case.business_domain.value,
            method_key=case.method_key,
            state=case.state.value,
            current_step=case.current_step,
            last_run_id=case.last_run_id,
            export_ref=case.export_ref,
            current_official_artifact_id=case.current_official_artifact_id,
            intake_verified_by=(
                case.intake_verified_by.value if case.intake_verified_by is not None else None
            ),
            intake_verified_at=(
                case.intake_verified_at.isoformat() if case.intake_verified_at is not None else None
            ),
            version=case.version,
            documents=[DocumentView.from_domain(d) for d in (documents or [])],
            artifacts=[ArtifactView.from_domain(a) for a in (artifacts or [])],
            notifications=[NotificationView.from_domain(n) for n in (notifications or [])],
        )
