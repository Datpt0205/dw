"""How many new requests one person may open, and when that stops them.

The two decisions these pin are the ones a reader would otherwise have to
guess at.

**The period is a calendar month cut in the rule pack's timezone.** A case
opened at 00:30 on the 1st in Vietnam is 17:30 on the last day of the previous
month in UTC. Slicing on UTC would file it under the month that just ended and
block somebody on the first night of a period they had not started using.

**A case someone else closed returns its slot.** The count goes down, which is
deliberate: the quota measures what you are occupying, not how many times you
typed. It also stops this mechanism punishing the same event twice — repeated
rejection is what rework support is for.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from dw_tender.application.preparation.intake_quota import (
    IntakeQuotaRules,
    OpenedCase,
    assess_quota,
    blocked_message,
    period_bounds,
)

HANOI = "Asia/Ho_Chi_Minh"


def _rules(
    *,
    threshold: int = 2,
    burst_threshold: int = 0,
    burst_window_days: int = 7,
    count_closed: bool = False,
    enabled_from: datetime | None = None,
) -> IntakeQuotaRules:
    return IntakeQuotaRules(
        policy_version="1.0.0",
        source="Quy chế mua sắm §4.2",
        enabled_from=enabled_from,
        timezone=HANOI,
        threshold=threshold,
        burst_window_days=burst_window_days,
        burst_threshold=burst_threshold,
        count_closed_unsuccessful=count_closed,
        explanation_min_chars=80,
        approver_role="procurement_head",
        escalate_after_hours=48,
        guidance="Gộp lại thành một yêu cầu sẽ nhanh hơn cho cả hai bên.",
    )


def _case(opened_at: datetime, *, closed: bool = False) -> OpenedCase:
    return OpenedCase(case_id=uuid.uuid4(), opened_at=opened_at, closed_unsuccessfully=closed)


NOW = datetime(2026, 9, 20, 3, 0, tzinfo=UTC)  # 10:00 giờ VN


# ------------------------------------------------------------ the counting --
def test_under_the_quota_nobody_is_blocked() -> None:
    result = assess_quota(
        cases=[_case(datetime(2026, 9, 3, tzinfo=UTC))], now=NOW, rules=_rules(threshold=2)
    )
    assert result.used == 1
    assert result.remaining == 1
    assert not result.blocked


def test_reaching_the_quota_blocks_the_next_one() -> None:
    """The threshold is reached, not exceeded: the 2nd of 2 already blocks a 3rd."""
    cases = [_case(datetime(2026, 9, 3, tzinfo=UTC)), _case(datetime(2026, 9, 11, tzinfo=UTC))]
    result = assess_quota(cases=cases, now=NOW, rules=_rules(threshold=2))
    assert result.used == 2
    assert result.remaining == 0
    assert result.blocked
    assert result.guidance, "a refusal always carries the way out"


def test_last_month_does_not_count_against_this_one() -> None:
    cases = [_case(datetime(2026, 8, 28, tzinfo=UTC)), _case(datetime(2026, 8, 30, tzinfo=UTC))]
    result = assess_quota(cases=cases, now=NOW, rules=_rules(threshold=2))
    assert result.used == 0
    assert not result.blocked


def test_zero_threshold_turns_the_whole_thing_off() -> None:
    cases = [_case(datetime(2026, 9, i, tzinfo=UTC)) for i in range(1, 10)]
    result = assess_quota(cases=cases, now=NOW, rules=_rules(threshold=0))
    assert not result.blocked
    assert result.used == 0


# ------------------------------------------------- a closed case gives back --
def test_a_case_someone_else_closed_returns_its_slot() -> None:
    cases = [
        _case(datetime(2026, 9, 3, tzinfo=UTC)),
        _case(datetime(2026, 9, 11, tzinfo=UTC), closed=True),
    ]
    result = assess_quota(cases=cases, now=NOW, rules=_rules(threshold=2))
    assert result.used == 1
    assert not result.blocked


def test_closed_cases_can_be_counted_when_the_rule_pack_says_so() -> None:
    cases = [
        _case(datetime(2026, 9, 3, tzinfo=UTC)),
        _case(datetime(2026, 9, 11, tzinfo=UTC), closed=True),
    ]
    result = assess_quota(cases=cases, now=NOW, rules=_rules(threshold=2, count_closed=True))
    assert result.used == 2
    assert result.blocked


# ----------------------------------------------------- the month boundary --
def test_the_month_is_cut_in_the_rule_packs_timezone() -> None:
    """00:30 on the 1st in Hanoi is 17:30 on the 30th in UTC — and counts as October."""
    now = datetime(2026, 10, 1, 3, 0, tzinfo=UTC)  # 10:00 VN, 1 Oct
    opened = datetime(2026, 9, 30, 17, 30, tzinfo=UTC)  # 00:30 VN, 1 Oct
    result = assess_quota(cases=[_case(opened)], now=now, rules=_rules(threshold=2))
    assert result.used == 1, "opened in October local time, so it belongs to October"
    assert result.period_label == "10/2026"


def test_the_last_minute_of_a_month_stays_in_that_month() -> None:
    now = datetime(2026, 10, 1, 3, 0, tzinfo=UTC)
    opened = datetime(2026, 9, 30, 16, 59, tzinfo=UTC)  # 23:59 VN, 30 Sep
    result = assess_quota(cases=[_case(opened)], now=now, rules=_rules(threshold=2))
    assert result.used == 0


def test_period_bounds_cover_a_december_rollover() -> None:
    start, end, label = period_bounds(datetime(2026, 12, 15, tzinfo=UTC), _rules())
    assert label == "12/2026"
    assert end > start
    assert (end - start).days in (31, 30)  # 31 days, minus/plus any offset shift


# ------------------------------------------------------------ not backdated --
def test_cases_opened_before_the_feature_was_switched_on_do_not_count() -> None:
    rules = _rules(threshold=2, enabled_from=datetime(2026, 9, 10, tzinfo=UTC))
    cases = [_case(datetime(2026, 9, 3, tzinfo=UTC)), _case(datetime(2026, 9, 11, tzinfo=UTC))]
    result = assess_quota(cases=cases, now=NOW, rules=rules)
    assert result.used == 1
    assert not result.blocked


# ------------------------------------------------------------------ burst --
def test_a_burst_cap_can_block_inside_an_unused_quota() -> None:
    """Three in a week trips the burst cap even though the month allows ten."""
    rules = _rules(threshold=10, burst_threshold=3, burst_window_days=7)
    cases = [_case(NOW - timedelta(days=d)) for d in (1, 2, 3)]
    result = assess_quota(cases=cases, now=NOW, rules=rules)
    assert result.blocked
    assert result.burst_used == 3
    assert "3 yêu cầu trong 7 ngày" in blocked_message(result)


def test_older_cases_fall_out_of_the_burst_window() -> None:
    rules = _rules(threshold=10, burst_threshold=3, burst_window_days=7)
    cases = [_case(NOW - timedelta(days=d)) for d in (1, 2, 30)]
    result = assess_quota(cases=cases, now=NOW, rules=rules)
    assert result.burst_used == 2
    assert not result.blocked


# ------------------------------------------------------------- the message --
def test_the_refusal_says_the_count_the_period_and_the_way_out() -> None:
    cases = [_case(datetime(2026, 9, 3, tzinfo=UTC)), _case(datetime(2026, 9, 11, tzinfo=UTC))]
    message = blocked_message(assess_quota(cases=cases, now=NOW, rules=_rules(threshold=2)))
    assert "2/2" in message
    assert "09/2026" in message
    assert "giải trình" in message
    assert "nhắn cho mình lý do" in message


def test_an_unavailable_assessment_blocks_nobody_and_says_it_is_unknown() -> None:
    from dw_tender.application.preparation.intake_quota import QuotaAssessment

    result = QuotaAssessment.unavailable(_rules())
    assert not result.blocked
    assert not result.available, "distinguishable from a clean slate in the logs"
