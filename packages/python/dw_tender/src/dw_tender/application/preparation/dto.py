"""API view models for the DW01 preparation slice."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from dw_tender.application.preparation.rework import ReworkAssessment
from dw_tender.application.preparation.rework_wording import (
    explanation_prompt,
    support_headline,
    support_lines,
)
from dw_tender.domain.preparation.entities import (
    PreparationArtifact,
    PreparationCase,
    PreparationDocument,
)
from dw_tender.domain.preparation.notifications import IntakeNotificationJob
from dw_tender.domain.preparation.rework import ExplanationRecord


class DocumentView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    kind: str
    title: str
    filename: str
    content_type: str
    size_bytes: int
    content_hash: str
    # Inline text for small text/* uploads so the UI can preview the source
    # document in a popup without a separate download round-trip.
    text_content: str | None = None

    @classmethod
    def from_domain(
        cls, document: PreparationDocument, text_content: str | None = None
    ) -> DocumentView:
        return cls(
            id=document.id.value,
            kind=document.kind.value,
            title=document.title,
            filename=document.filename,
            content_type=document.content_type,
            size_bytes=document.size_bytes,
            content_hash=document.content_hash,
            text_content=text_content,
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


class ReworkSupportView(BaseModel):
    """What the support ladder says about the caller.

    Rendered on the caller's own case page. Deliberately carries no identity
    of any kind — it is only ever built for the person asking about
    themselves, and a view with a user id on it is one refactor away from
    being rendered on somebody else's screen.
    """

    model_config = ConfigDict(extra="forbid")

    # False means the tally could not be computed. The UI must treat that as
    # "say nothing", never as "all clear" — the two are different facts.
    available: bool
    level: str
    count: int
    window_days: int
    nudge_count: int
    block_count: int
    nudge_threshold: int
    block_threshold: int
    policy_version: str
    top_reason_code: str | None = None
    top_reason_label: str = ""
    headline: str = ""
    lines: list[str] = []
    prompt: str = ""
    explanation_min_chars: int = 0

    @classmethod
    def from_assessment(cls, assessment: ReworkAssessment, *, min_chars: int) -> ReworkSupportView:
        return cls(
            available=assessment.available,
            level=assessment.level.value,
            count=assessment.count,
            window_days=assessment.window_days,
            nudge_count=assessment.nudge_count,
            block_count=assessment.block_count,
            nudge_threshold=assessment.nudge_threshold,
            block_threshold=assessment.block_threshold,
            policy_version=assessment.policy_version,
            top_reason_code=assessment.top_reason_code,
            top_reason_label=assessment.top_reason_label,
            # Every user-facing sentence comes from the one wording module —
            # never assembled here, so the phrasing test covers all of it.
            headline=support_headline(assessment),
            lines=support_lines(assessment),
            prompt=explanation_prompt(assessment),
            explanation_min_chars=min_chars,
        )


class ExplanationView(BaseModel):
    """One pending explanation, as its reviewer sees it.

    Carries the author's user id because a reviewer has to know whose queue
    they are unblocking; the requester-facing ``ReworkSupportView`` carries no
    identity at all, and the two must not be merged for that reason.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    case_id: UUID | None
    creator_user_id: UUID
    context_text: str
    difficulty_text: str
    support_request_text: str
    block_count: int
    nudge_count: int
    top_reason_code: str
    policy_version: str
    submitted_at: str
    status: str

    @classmethod
    def from_domain(cls, record: ExplanationRecord) -> ExplanationView:
        return cls(
            id=record.id,
            case_id=record.case_id.value if record.case_id is not None else None,
            creator_user_id=record.creator_user_id.value,
            context_text=record.context_text,
            difficulty_text=record.difficulty_text,
            support_request_text=record.support_request_text,
            block_count=record.block_count,
            nudge_count=record.nudge_count,
            top_reason_code=record.top_reason_code,
            policy_version=record.policy_version,
            submitted_at=record.submitted_at.isoformat(),
            status=record.status.value,
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
    # Who filed the request — drives "only my own cases" visibility for
    # requesters (approvers see the whole workspace).
    created_by: UUID
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
        document_texts: dict[UUID, str] | None = None,
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
            created_by=case.created_by.value,
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
            documents=[
                DocumentView.from_domain(d, (document_texts or {}).get(d.id.value))
                for d in (documents or [])
            ],
            artifacts=[ArtifactView.from_domain(a) for a in (artifacts or [])],
            notifications=[NotificationView.from_domain(n) for n in (notifications or [])],
        )
