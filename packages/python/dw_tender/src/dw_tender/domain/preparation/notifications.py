"""Durable notification jobs emitted by the DW01 intake approval lifecycle."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_tender.domain.value_objects.ids import PreparationCaseId


class IntakeNotificationType(StrEnum):
    APPROVAL_REQUESTED = "intake.approval_requested"
    APPROVAL_ESCALATED = "intake.approval_escalated"
    APPROVED = "intake.approved"
    REJECTED = "intake.rejected"


class NotificationJobStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class IntakeNotificationJob:
    id: uuid.UUID
    tenant_id: TenantId
    workspace_id: WorkspaceId
    case_id: PreparationCaseId
    event_type: IntakeNotificationType
    recipient_user_id: UserId
    due_at: datetime
    idempotency_key: str
    payload: dict[str, object] = field(default_factory=dict)
    status: NotificationJobStatus = NotificationJobStatus.QUEUED
    attempts: int = 0
    max_attempts: int = 5
    last_error: str | None = None
    slack_channel_id: str | None = None
    slack_message_ts: str | None = None
    claimed_at: datetime | None = None
    sent_at: datetime | None = None
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class IntakeNotificationDelivery:
    """A claimed job plus the stable Slack-directory key for its recipient."""

    job: IntakeNotificationJob
    recipient_subject: str
    case_state: str
