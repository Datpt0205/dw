"""Catching a repeat purchase — and, more importantly, not crying wolf.

A false alarm here implies a colleague split a package to dodge a threshold.
That accusation is remembered; being asked for one paragraph of context is
not. So these tests spend more effort on what must NOT trigger than on what
must.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from dw_tender.adapters.preparation.rules_loader import load_procurement_rules
from dw_tender.application.preparation.repeat_purchase import PastPurchase, find_repeat

pytestmark = pytest.mark.unit

RULES = load_procurement_rules(
    Path(__file__).resolve().parents[5]
    / "configs"
    / "policies"
    / "dw01"
    / "procurement_rules_v1.yaml"
)

NOW = datetime(2026, 8, 18, tzinfo=UTC)
BIG = 780_000_000  # above the rule pack's min_value


def _past(
    title: str,
    days_ago: int,
    domain: str = "information_technology",
    value: int = BIG,
) -> PastPurchase:
    return PastPurchase(
        case_id=uuid.uuid4(),
        title=title,
        created_at=NOW - timedelta(days=days_ago),
        estimated_value_minor=value,
        business_domain=domain,
        owner_name="Nguyễn Văn An",
    )


def _find(
    title: str,
    history: list[PastPurchase],
    value: int = BIG,
    domain: str = "information_technology",
):
    return find_repeat(
        title=title,
        business_domain=domain,
        estimated_value_minor=value,
        now=NOW,
        history=history,
        rules=RULES,
    )


# ------------------------------------------------------------- it catches --
def test_the_same_thing_bought_three_weeks_ago_is_flagged() -> None:
    finding = _find(
        "Mua 25 bộ máy trạm cho nhóm dự án",
        [_past("Mua 30 bộ máy trạm cho nhóm phát triển", days_ago=21)],
    )
    assert finding is not None
    assert finding.days_ago == 21
    assert "máy trạm" in finding.earlier_title


def test_the_question_asks_for_context_not_an_explanation_of_wrongdoing() -> None:
    finding = _find(
        "Mua 25 bộ máy trạm cho nhóm dự án",
        [_past("Mua 30 bộ máy trạm cho nhóm phát triển", days_ago=21)],
    )
    assert finding is not None
    text = finding.question.lower()
    assert "phục vụ bộ phận nào" in text
    for accusation in ("chia nhỏ", "vi phạm", "sai phạm", "lách"):
        assert accusation not in text, "a repeat purchase is not an allegation"


def test_it_names_the_earlier_case_so_a_person_can_check() -> None:
    earlier = _past("Mua 30 bộ máy trạm cho nhóm phát triển", days_ago=10)
    finding = _find("Mua 25 bộ máy trạm cho nhóm kiểm thử", [earlier])
    assert finding is not None
    assert finding.earlier_case_id == earlier.case_id
    assert finding.as_clarification()["related_case_id"] == str(earlier.case_id)
    assert finding.as_clarification()["blocking"] is True


def test_the_closest_match_wins_when_several_are_near() -> None:
    exact = _past("Mua 30 bộ máy trạm cho nhóm phát triển", days_ago=30)
    looser = _past("Mua 12 bộ máy trạm và màn hình cho phòng kế toán", days_ago=5)
    finding = _find("Mua 30 bộ máy trạm cho nhóm phát triển", [looser, exact])
    assert finding is not None
    assert finding.earlier_case_id == exact.case_id


# --------------------------------------------------- it stays quiet when --
def test_a_different_kind_of_purchase_is_not_a_repeat() -> None:
    assert _find("Mua 25 bộ máy trạm", [_past("Thuê dịch vụ bảo trì điện", days_ago=5)]) is None


def test_an_older_purchase_is_outside_the_window() -> None:
    assert (
        _find(
            "Mua 25 bộ máy trạm cho nhóm dự án",
            [_past("Mua 30 bộ máy trạm cho nhóm phát triển", days_ago=200)],
        )
        is None
    )


def test_another_department_buying_the_same_thing_is_not_this_units_repeat() -> None:
    assert (
        _find(
            "Mua 25 bộ máy trạm cho nhóm dự án",
            [_past("Mua 30 bộ máy trạm cho nhóm phát triển", days_ago=10, domain="operations")],
        )
        is None
    )


def test_small_recurring_purchases_are_left_alone() -> None:
    """Stationery bought every month is normal; flagging it trains people to ignore flags."""
    assert (
        _find(
            "Mua vật tư văn phòng quý 3",
            [_past("Mua vật tư văn phòng quý 2", days_ago=20, value=5_000_000)],
            value=5_000_000,
        )
        is None
    )


def test_no_history_is_not_a_finding() -> None:
    assert _find("Mua 25 bộ máy trạm", []) is None


def test_a_future_dated_record_does_not_count() -> None:
    """Clock skew must not manufacture a repeat out of nothing."""
    future = PastPurchase(
        case_id=uuid.uuid4(),
        title="Mua 30 bộ máy trạm cho nhóm phát triển",
        created_at=NOW + timedelta(days=3),
        estimated_value_minor=BIG,
        business_domain="information_technology",
    )
    assert _find("Mua 30 bộ máy trạm cho nhóm phát triển", [future]) is None


def test_the_rule_can_be_switched_off_from_the_rule_pack() -> None:
    """Procurement turns this off without a deploy — and it must actually go quiet."""
    off = RULES.__class__(**{**RULES.__dict__, "repeat_lookback_days": 0})
    assert (
        find_repeat(
            title="Mua 25 bộ máy trạm",
            business_domain="information_technology",
            estimated_value_minor=BIG,
            now=NOW,
            history=[_past("Mua 30 bộ máy trạm", days_ago=3)],
            rules=off,
        )
        is None
    )


def test_the_shipped_rule_pack_actually_carries_the_thresholds() -> None:
    assert RULES.repeat_lookback_days > 0
    assert 0 < RULES.repeat_similarity <= 1
    assert RULES.watches_repeat_purchase(BIG)
    assert not RULES.watches_repeat_purchase(1_000_000)
