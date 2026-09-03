"""DW01 domain: returned cases, and the written context that unblocks them.

Two records, and the difference between them is the whole design.

A ``ReworkEvent`` is a fact: a named person returned a named case at a named
moment for a named reason. Facts do not change. The only mutation it ever
accepts is being marked as a mis-click — and even then the original stays
readable, because the correction is itself a fact worth keeping.

An ``ExplanationRecord`` is a fact plus a pending decision. The text a person
wrote is immutable for the same reason; the decision on it is not yet made,
and making it is a transition with rules — decided once, never by its own
author, never without a comment.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from dw_kernel.errors import ConflictError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_tender.domain.exceptions import TenderDomainError
from dw_tender.domain.value_objects.ids import PreparationCaseId


class ReworkCheckpoint(StrEnum):
    """Where a case was handed back.

    Only the three points at which a human decides. Automated gates are
    deliberately absent: failing a gate mid-draft is the tool working, and
    counting it would penalise people for using it as intended.
    """

    INTAKE = "intake"
    CP1 = "cp1"
    CP2 = "cp2"


class ExplanationStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class ReworkEvent:
    """One case handed back to its author.

    Frozen: the count that can stop someone from working has to rest on
    records nothing in the application layer is able to rewrite. The database
    enforces the same thing independently — the runtime role holds no DELETE
    here, and UPDATE only on the three void columns.
    """

    id: uuid.UUID
    tenant_id: TenantId
    workspace_id: WorkspaceId
    case_id: PreparationCaseId
    # Whose case it was. This — not whoever clicked submit — is the key the
    # tally groups by, so filing a case on someone's behalf never lands on the
    # wrong person.
    creator_user_id: UserId
    decided_by_user_id: UserId
    checkpoint: ReworkCheckpoint
    reason_code: str
    reason_text: str
    policy_version: str
    occurred_at: datetime
    voided_at: datetime | None = None
    voided_by: UserId | None = None
    void_reason: str = ""

    def __post_init__(self) -> None:
        if not self.reason_text.strip():
            raise TenderDomainError("a returned case must carry the approver's reason")
        if self.occurred_at.tzinfo is None:
            raise TenderDomainError("rework event timestamp must carry a timezone")

    @property
    def voided(self) -> bool:
        """Marked as a mis-click: still on the record, out of the tally."""
        return self.voided_at is not None


@dataclass(slots=True)
class ExplanationRecord:
    """What someone wrote about what is getting in the way, and its decision.

    Everything above ``status`` is written once at submission and never
    touched again. ``decide`` is the only mutator, and it is the same shape as
    ``ApprovalRequest.decide``: a decision is made exactly once.
    """

    id: uuid.UUID
    tenant_id: TenantId
    workspace_id: WorkspaceId
    case_id: PreparationCaseId | None
    creator_user_id: UserId
    context_text: str
    difficulty_text: str
    support_request_text: str
    policy_version: str
    submitted_at: datetime
    # The events that had pushed this person over at the moment they wrote
    # this. Captured now on purpose: reopened three weeks later the window has
    # moved on, and the explanation would appear to answer a different set of
    # facts than the one it was actually written about.
    counted_event_ids: tuple[uuid.UUID, ...] = ()
    nudge_count: int = 0
    block_count: int = 0
    top_reason_code: str = ""
    status: ExplanationStatus = ExplanationStatus.PENDING
    decided_by: UserId | None = None
    decided_at: datetime | None = None
    decision_comment: str = ""
    extras: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.context_text.strip():
            raise TenderDomainError("an explanation needs the context in the author's words")

    @property
    def decided(self) -> bool:
        return self.status is not ExplanationStatus.PENDING

    def decide(
        self,
        *,
        approve: bool,
        decided_by: UserId,
        decided_at: datetime,
        comment: str,
    ) -> None:
        """Approve or turn back one explanation.

        Three refusals, and each one is about the same thing — a decision that
        unblocks a colleague has to be attributable to somebody other than the
        person it unblocks, and has to say something back to them.
        """
        if self.decided:
            raise ConflictError(
                "this explanation has already been decided",
                details={"explanation_id": str(self.id), "status": self.status.value},
            )
        if decided_by == self.creator_user_id:
            raise ConflictError(
                "separation of duties: the author cannot decide their own explanation",
                details={"explanation_id": str(self.id)},
            )
        if not comment.strip():
            raise ConflictError(
                "a decision on an explanation needs a note back to the author",
                details={"explanation_id": str(self.id)},
            )
        if decided_at.tzinfo is None:
            raise TenderDomainError("decision timestamp must carry a timezone")
        self.status = ExplanationStatus.APPROVED if approve else ExplanationStatus.REJECTED
        self.decided_by = decided_by
        self.decided_at = decided_at
        self.decision_comment = comment.strip()
