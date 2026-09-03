"""An approved addendum has to reach the suppliers and move the clock.

Before this, CP3 approval wrote an ``addendum_decision`` artifact and stopped.
Two consequences, both invisible from inside the system: nobody holding the
invitation was ever told, and an approved extension left ``bids_close_at``
where it was, so the register closed on the old moment while a signed document
promised otherwise.

These pin the effect, not the intention — what was sent, and where the clock
ended up.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_tender.application.preparation.handlers import (
    _addendum_effect_lines,
    _build_addendum_email_body,
)
from dw_tender.domain.exceptions import TenderDomainError
from dw_tender.domain.preparation.entities import (
    BusinessDomain,
    CaseState,
    PreparationCase,
    ProcurementType,
)
from dw_tender.domain.value_objects.ids import PreparationCaseId

pytestmark = pytest.mark.unit

CLOSES = datetime(2026, 9, 1, 17, 0, tzinfo=UTC)


def _case(state: CaseState = CaseState.CP3_PENDING, closes: datetime | None = CLOSES):
    case = PreparationCase(
        id=PreparationCaseId(uuid.uuid4()),
        tenant_id=TenantId(uuid.uuid4()),
        workspace_id=WorkspaceId(uuid.uuid4()),
        title="Mua màn hình cho team AI FDX",
        created_by=UserId(uuid.uuid4()),
        estimated_value_minor=300_000_000_000,
        deadline="90 ngày",
        procurement_type=ProcurementType.GOODS,
        business_domain=BusinessDomain.INFORMATION_TECHNOLOGY,
        state=state,
    )
    case.bids_close_at = closes
    return case


# ------------------------------------------------------- the clock moves --
def test_an_approved_extension_moves_the_closing_moment() -> None:
    case = _case()
    case.resolve_cp3(extend_bids_by_days=10)
    assert case.bids_close_at == CLOSES + timedelta(days=10)
    assert case.state is CaseState.PUBLISHED


def test_an_addendum_with_no_extension_leaves_the_clock_alone() -> None:
    case = _case()
    case.resolve_cp3()
    assert case.bids_close_at == CLOSES


def test_the_delivery_deadline_is_not_touched() -> None:
    """Extending nộp thầu is not extending giao hàng."""
    case = _case()
    case.resolve_cp3(extend_bids_by_days=10)
    assert case.deadline == "90 ngày"


def test_a_case_with_no_closing_moment_survives_an_extension() -> None:
    """Older cases published before the window was recorded must not crash."""
    case = _case(closes=None)
    case.resolve_cp3(extend_bids_by_days=10)
    assert case.bids_close_at is None
    assert case.state is CaseState.PUBLISHED


def test_only_a_case_awaiting_cp3_can_resolve_it() -> None:
    case = _case(CaseState.PUBLISHED)
    with pytest.raises(TenderDomainError):
        case.resolve_cp3(extend_bids_by_days=10)


def test_the_version_bumps_exactly_once() -> None:
    """Two bumps would trip the optimistic lock the repository enforces."""
    case = _case()
    before = case.version
    case.resolve_cp3(extend_bids_by_days=10)
    assert case.version == before + 1


# ---------------------------------------------- what the suppliers read --
def test_the_email_never_names_the_other_bidders() -> None:
    body = _build_addendum_email_body(_case(), "Gia hạn nộp thầu thêm 10 ngày", "Hạn lùi 10 ngày")
    for rival in ("Thiết bị Việt", "Minh Long", "Sao Mai"):
        assert rival not in body


def test_the_email_carries_the_new_closing_moment() -> None:
    case = _case()
    case.resolve_cp3(extend_bids_by_days=10)
    body = _build_addendum_email_body(case, "Gia hạn nộp thầu thêm 10 ngày", "")
    assert "11/09/2026" in body
    assert "SỬA ĐỔI" in body


# --------------------------------------- what the requester is told back --
def test_the_reply_names_who_was_sent_to_and_the_new_date() -> None:
    lines = _addendum_effect_lines(
        approve=True,
        issued={"issued_to": "Thiết bị Việt, Minh Long, Sao Mai"},
        extend_days=10,
        closed_before=CLOSES,
        closes_at=CLOSES + timedelta(days=10),
    )
    joined = " ".join(lines)
    assert "Thiết bị Việt, Minh Long, Sao Mai" in joined
    assert "11/09/2026" in joined


def test_an_undelivered_addendum_says_so_rather_than_claiming_success() -> None:
    lines = _addendum_effect_lines(
        approve=True, issued={}, extend_days=0, closed_before=None, closes_at=None
    )
    assert any("Chưa gửi được" in line for line in lines)


def test_an_extension_with_nowhere_to_land_is_reported_honestly() -> None:
    lines = _addendum_effect_lines(
        approve=True,
        issued={"issued_to": "FPT"},
        extend_days=10,
        closed_before=None,
        closes_at=None,
    )
    assert any("chưa có mốc đóng sổ" in line for line in lines)


def test_a_rejected_addendum_claims_no_effect_at_all() -> None:
    lines = _addendum_effect_lines(
        approve=False,
        issued={},
        extend_days=10,
        closed_before=CLOSES,
        closes_at=CLOSES,
    )
    assert lines == ["Addendum không có hiệu lực; HSMT giữ nguyên."]
