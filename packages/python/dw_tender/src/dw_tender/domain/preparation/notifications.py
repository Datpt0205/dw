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
    # P3 activity trace: a generic per-step progress card for the case owner.
    # Payload carries {"title", "heading", "lines"}; content is SYSTEM-BUILT
    # from real node events (gate results, artifact versions) — never model text.
    RUN_PROGRESS = "run.progress"
    # P4 Slack approvals: decision card for the approver with Duyệt/Từ chối
    # buttons. Payload: {"title", "checkpoint": "CP1"|"CP2", "lines", "case_id"}.
    CP_APPROVAL_REQUESTED = "cp.approval_requested"
    # Addendum proposal from the requester: procurement (Bình) decides whether
    # to draft it — the requester never files CP3 paperwork directly (role fix:
    # An proposes, procurement drafts, authority decides). Payload:
    # {"title", "lines", "buttons", "case_id"}.
    ADDENDUM_PROPOSED = "addendum.proposed"
    # The law moved under a package that is still waiting to be signed. Advice,
    # not an action: the approval stands and the person decides what to do,
    # because a web result is not grounds to tear up work already under way.
    # Payload: {"title", "lines", "case_id", "article_ref", "before", "after"}.
    LAW_CHANGE_DETECTED = "law.change_detected"
    # Rework support. These three are attached to a PERSON, not to a case
    # state: the case_id on the job only says where the card was raised from.
    # The Slack consumer's staleness check must skip them for that reason —
    # otherwise the card is cancelled the moment the case moves on.
    #
    # Offered to the requester when returns start clustering. Advice, not an
    # obstacle: work continues. Payload: {"lines", "count", "window_days"}.
    REWORK_SUPPORT_OFFERED = "rework.support_offered"
    # Someone is now waiting on a written explanation before they can file
    # again. Goes to whoever the rule pack says can help — never to the person
    # who is blocked. Payload: {"explanation_id", "lines", "block_count"}.
    REWORK_SUPPORT_REQUIRED = "rework.support_required"
    # That explanation has been sitting unread past the deadline. Blocked and
    # ignored is the worst state this mechanism can produce, so it gets loud.
    # Payload: {"explanation_id"}.
    REWORK_EXPLANATION_ESCALATED = "rework.explanation_escalated"


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
