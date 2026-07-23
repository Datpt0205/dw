"""Approval aggregate: human decisions gating critical side effects (§11.3).

Invariant: a request is decided exactly once; decisions are immutable facts.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from dw_kernel.errors import ConflictError
from dw_kernel.ids import TenantId, UserId, WorkspaceId


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class DecisionOutcome(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class ApprovalDecision:
    """Immutable record of one human decision."""

    id: uuid.UUID
    request_id: uuid.UUID
    tenant_id: TenantId
    workspace_id: WorkspaceId
    decided_by: UserId
    outcome: DecisionOutcome
    comment: str
    decided_at: datetime


@dataclass(slots=True)
class ApprovalRequest:
    """A pending question for a human; pauses the workflow that raised it."""

    id: uuid.UUID
    tenant_id: TenantId
    workspace_id: WorkspaceId
    approval_type: str
    requested_by: UserId
    reason: str
    payload: dict[str, object] = field(default_factory=dict)
    run_id: uuid.UUID | None = None
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: datetime | None = None
    decided_at: datetime | None = None
    version: int = 1

    def _require_pending(self) -> None:
        if self.status is not ApprovalStatus.PENDING:
            raise ConflictError(
                "approval request already decided",
                details={"request_id": str(self.id), "status": self.status.value},
            )

    def decide(
        self,
        *,
        decision_id: uuid.UUID,
        decided_by: UserId,
        outcome: DecisionOutcome,
        decided_at: datetime,
        comment: str = "",
    ) -> ApprovalDecision:
        """Apply a human decision; returns the immutable decision record."""
        self._require_pending()
        self.status = (
            ApprovalStatus.APPROVED
            if outcome is DecisionOutcome.APPROVED
            else ApprovalStatus.REJECTED
        )
        self.decided_at = decided_at
        self.version += 1
        return ApprovalDecision(
            id=decision_id,
            request_id=self.id,
            tenant_id=self.tenant_id,
            workspace_id=self.workspace_id,
            decided_by=decided_by,
            outcome=outcome,
            comment=comment,
            decided_at=decided_at,
        )

    def cancel(self) -> None:
        self._require_pending()
        self.status = ApprovalStatus.CANCELLED
        self.version += 1
