import uuid
from datetime import UTC, datetime

import pytest

from dw_kernel.errors import ConflictError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_platform.domain.approval import (
    ApprovalRequest,
    ApprovalStatus,
    DecisionOutcome,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)


def make_request() -> ApprovalRequest:
    return ApprovalRequest(
        id=uuid.uuid4(),
        tenant_id=TenantId(uuid.uuid4()),
        workspace_id=WorkspaceId(uuid.uuid4()),
        approval_type="work_ops.dispatch_actions",
        requested_by=UserId(uuid.uuid4()),
        reason="Cross-department task requires approval",
    )


def test_approve_transitions_and_returns_decision() -> None:
    request = make_request()
    approver = UserId(uuid.uuid4())
    decision = request.decide(
        decision_id=uuid.uuid4(),
        decided_by=approver,
        outcome=DecisionOutcome.APPROVED,
        decided_at=NOW,
        comment="OK",
    )
    assert request.status is ApprovalStatus.APPROVED
    assert request.decided_at == NOW
    assert request.version == 2
    assert decision.outcome is DecisionOutcome.APPROVED
    assert decision.request_id == request.id


def test_reject_transitions() -> None:
    request = make_request()
    request.decide(
        decision_id=uuid.uuid4(),
        decided_by=UserId(uuid.uuid4()),
        outcome=DecisionOutcome.REJECTED,
        decided_at=NOW,
    )
    assert request.status is ApprovalStatus.REJECTED


def test_double_decision_conflicts() -> None:
    request = make_request()
    request.decide(
        decision_id=uuid.uuid4(),
        decided_by=UserId(uuid.uuid4()),
        outcome=DecisionOutcome.APPROVED,
        decided_at=NOW,
    )
    with pytest.raises(ConflictError, match="already decided"):
        request.decide(
            decision_id=uuid.uuid4(),
            decided_by=UserId(uuid.uuid4()),
            outcome=DecisionOutcome.REJECTED,
            decided_at=NOW,
        )


def test_cancel_only_when_pending() -> None:
    request = make_request()
    request.cancel()
    assert request.status is ApprovalStatus.CANCELLED
    with pytest.raises(ConflictError):
        request.cancel()
