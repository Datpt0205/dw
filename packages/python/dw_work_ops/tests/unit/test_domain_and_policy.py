import uuid
from datetime import UTC, datetime

import pytest

from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_work_ops.domain.entities import (
    ActionItem,
    ActionStatus,
    MeetingSession,
    MeetingStatus,
    ResolvedAssignee,
)
from dw_work_ops.domain.exceptions import UnresolvedAssigneeError, WorkOpsDomainError
from dw_work_ops.domain.policies import (
    CanAutoDispatchAction,
    DispatchPolicyContext,
)
from dw_work_ops.domain.value_objects.confidence import Confidence, RiskLevel
from dw_work_ops.domain.value_objects.ids import ActionItemId, MeetingId

pytestmark = pytest.mark.unit

NOW = datetime(2026, 7, 23, 9, 0, tzinfo=UTC)


def make_meeting() -> MeetingSession:
    return MeetingSession(
        id=MeetingId(uuid.uuid4()),
        tenant_id=TenantId(uuid.uuid4()),
        workspace_id=WorkspaceId(uuid.uuid4()),
        title="Họp giao ban",
        occurred_at=NOW,
        created_by=UserId(uuid.uuid4()),
    )


def make_action(**overrides: object) -> ActionItem:
    defaults: dict[str, object] = {
        "id": ActionItemId(uuid.uuid4()),
        "tenant_id": TenantId(uuid.uuid4()),
        "workspace_id": WorkspaceId(uuid.uuid4()),
        "meeting_id": MeetingId(uuid.uuid4()),
        "title": "Soạn hồ sơ RFQ",
        "assignee": ResolvedAssignee(
            person_id=UserId(uuid.uuid4()),
            display_name="Trần Thị Bình",
            department="mua-hang",
            confidence=Confidence(0.95),
        ),
    }
    defaults.update(overrides)
    return ActionItem(**defaults)  # type: ignore[arg-type]


def test_meeting_lifecycle_transitions() -> None:
    meeting = make_meeting()
    with pytest.raises(WorkOpsDomainError, match="without a transcript"):
        meeting.start_processing(uuid.uuid4())
    from dw_work_ops.domain.value_objects.ids import TranscriptArtifactId

    meeting.attach_transcript(TranscriptArtifactId(uuid.uuid4()))
    run_id = uuid.uuid4()
    meeting.start_processing(run_id)

    def status_of(m: MeetingSession) -> MeetingStatus:
        return m.status

    assert status_of(meeting) is MeetingStatus.PROCESSING
    assert meeting.last_run_id == run_id
    meeting.mark_actions_ready({"headline": "x"})
    assert status_of(meeting) is MeetingStatus.ACTIONS_READY
    meeting.complete()
    assert status_of(meeting) is MeetingStatus.COMPLETED


def test_action_dispatch_requires_approved_and_assignee() -> None:
    action = make_action()
    with pytest.raises(WorkOpsDomainError, match="only approved"):
        action.mark_dispatched()
    action.approve()
    action.mark_dispatched()
    assert action.status is ActionStatus.DISPATCHED

    unassigned = make_action(assignee=None)
    unassigned.approve()
    with pytest.raises(UnresolvedAssigneeError):
        unassigned.mark_dispatched()


def test_policy_same_department_high_confidence_still_a2_review() -> None:
    """POC autonomy A2: even a perfect action goes through human review."""
    policy = CanAutoDispatchAction()
    decision = policy.evaluate(
        make_action(),
        DispatchPolicyContext(requester_department="mua-hang"),
    )
    assert decision.requires_approval
    assert decision.reasons == ("autonomy_a2_requires_review",)


def test_policy_flags_cross_department_and_low_confidence() -> None:
    policy = CanAutoDispatchAction()
    action = make_action(
        assignee=ResolvedAssignee(
            person_id=UserId(uuid.uuid4()),
            display_name="Nguyễn Văn An",
            department="kinh-doanh",
            confidence=Confidence(0.75),
        ),
        due_date_inferred=True,
        risk_level=RiskLevel.MEDIUM,
    )
    decision = policy.evaluate(action, DispatchPolicyContext(requester_department="dieu-hanh"))
    assert decision.requires_approval
    assert set(decision.reasons) >= {
        "risk_not_low",
        "cross_department",
        "low_assignee_confidence",
        "due_date_inferred",
    }


def test_policy_unresolved_assignee_flagged() -> None:
    decision = CanAutoDispatchAction().evaluate(
        make_action(assignee=None),
        DispatchPolicyContext(requester_department="mua-hang"),
    )
    assert "assignee_unresolved" in decision.reasons
