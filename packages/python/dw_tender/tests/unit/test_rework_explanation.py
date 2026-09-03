"""The rules around deciding an explanation.

Unblocking a colleague is a decision with consequences, so it carries the same
guards the DW01 checkpoints already carry: decided once, never by its author,
never silently. These tests exist because each of those is exactly one `if`
away from disappearing in a refactor.
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime

import pytest

from dw_kernel.errors import ConflictError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_tender.domain.exceptions import TenderDomainError
from dw_tender.domain.preparation.rework import (
    ExplanationRecord,
    ExplanationStatus,
    ReworkCheckpoint,
    ReworkEvent,
)
from dw_tender.domain.value_objects.ids import PreparationCaseId

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 20, tzinfo=UTC)
AUTHOR = UserId(uuid.uuid4())
APPROVER = UserId(uuid.uuid4())


def _record(
    *,
    creator_user_id: UserId = AUTHOR,
    context_text: str = "Đầu bài từ bộ phận yêu cầu gửi sang còn thiếu số hiệu phê duyệt.",
    counted_event_ids: tuple[uuid.UUID, ...] = (),
) -> ExplanationRecord:
    return ExplanationRecord(
        id=uuid.uuid4(),
        tenant_id=TenantId(uuid.uuid4()),
        workspace_id=WorkspaceId(uuid.uuid4()),
        case_id=PreparationCaseId(uuid.uuid4()),
        creator_user_id=creator_user_id,
        context_text=context_text,
        difficulty_text="Mỗi lần phải hỏi lại mất hai ngày.",
        support_request_text="Nhờ bên mua sắm rà giúp trước khi nộp.",
        policy_version="1.0.0",
        submitted_at=NOW,
        counted_event_ids=counted_event_ids,
    )


def _event(
    *,
    reason_text: str = "Dự toán lệch với đề nghị mua sắm.",
    occurred_at: datetime = NOW,
    voided_at: datetime | None = None,
    voided_by: UserId | None = None,
    void_reason: str = "",
) -> ReworkEvent:
    return ReworkEvent(
        id=uuid.uuid4(),
        tenant_id=TenantId(uuid.uuid4()),
        workspace_id=WorkspaceId(uuid.uuid4()),
        case_id=PreparationCaseId(uuid.uuid4()),
        creator_user_id=AUTHOR,
        decided_by_user_id=APPROVER,
        checkpoint=ReworkCheckpoint.INTAKE,
        reason_code="budget_mismatch",
        reason_text=reason_text,
        policy_version="1.0.0",
        occurred_at=occurred_at,
        voided_at=voided_at,
        voided_by=voided_by,
        void_reason=void_reason,
    )


# --- the returned-case record ----------------------------------------------


def test_a_returned_case_must_carry_the_approvers_reason() -> None:
    with pytest.raises(TenderDomainError):
        _event(reason_text="   ")


def test_a_naive_timestamp_is_refused() -> None:
    """Windows are measured in hours; an ambiguous moment corrupts the count."""
    with pytest.raises(TenderDomainError):
        _event(occurred_at=datetime(2026, 9, 20))


def test_a_fresh_event_is_not_voided() -> None:
    assert _event().voided is False


def test_marking_a_mis_click_keeps_the_original_readable() -> None:
    event = _event(voided_at=NOW, voided_by=APPROVER, void_reason="Bấm nhầm nút.")
    assert event.voided is True
    assert event.reason_text == "Dự toán lệch với đề nghị mua sắm."


def test_the_record_cannot_be_rewritten() -> None:
    event = _event()
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.reason_text = "đổi ý"  # type: ignore[misc]


# --- deciding an explanation -----------------------------------------------


def test_an_explanation_needs_the_context_in_the_authors_words() -> None:
    with pytest.raises(TenderDomainError):
        _record(context_text="  ")


def test_approving_records_who_when_and_what_they_said() -> None:
    record = _record()
    record.decide(approve=True, decided_by=APPROVER, decided_at=NOW, comment="Đã trao đổi, ổn.")
    assert record.status is ExplanationStatus.APPROVED
    assert record.decided_by == APPROVER
    assert record.decision_comment == "Đã trao đổi, ổn."


def test_turning_one_back_is_also_a_decision() -> None:
    record = _record()
    record.decide(approve=False, decided_by=APPROVER, decided_at=NOW, comment="Cần rõ hơn.")
    assert record.status is ExplanationStatus.REJECTED
    assert record.decided is True


def test_an_explanation_is_decided_exactly_once() -> None:
    record = _record()
    record.decide(approve=True, decided_by=APPROVER, decided_at=NOW, comment="ok")
    with pytest.raises(ConflictError):
        record.decide(approve=False, decided_by=APPROVER, decided_at=NOW, comment="đổi ý")


def test_a_rejected_explanation_cannot_be_quietly_re_approved() -> None:
    record = _record()
    record.decide(approve=False, decided_by=APPROVER, decided_at=NOW, comment="chưa rõ")
    with pytest.raises(ConflictError):
        record.decide(approve=True, decided_by=APPROVER, decided_at=NOW, comment="thôi được")
    assert record.status is ExplanationStatus.REJECTED


def test_the_author_cannot_unblock_themselves() -> None:
    record = _record()
    with pytest.raises(ConflictError):
        record.decide(approve=True, decided_by=AUTHOR, decided_at=NOW, comment="tự duyệt")
    assert record.status is ExplanationStatus.PENDING


def test_a_decision_must_say_something_back() -> None:
    """Silence on the way out is what makes the whole thing feel punitive."""
    record = _record()
    with pytest.raises(ConflictError):
        record.decide(approve=True, decided_by=APPROVER, decided_at=NOW, comment="   ")


def test_a_refused_decision_leaves_the_record_untouched() -> None:
    record = _record()
    with pytest.raises(ConflictError):
        record.decide(approve=True, decided_by=AUTHOR, decided_at=NOW, comment="x")
    assert record.decided_by is None
    assert record.decided_at is None
    assert record.decision_comment == ""


def test_the_counted_events_are_carried_on_the_record() -> None:
    ids = (uuid.uuid4(), uuid.uuid4())
    assert _record(counted_event_ids=ids).counted_event_ids == ids
