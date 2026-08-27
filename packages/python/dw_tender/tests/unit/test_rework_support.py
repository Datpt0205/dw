"""Counting returned cases — and, above all, not blocking the wrong person.

Blocking someone wrongly costs far more than missing a pattern: a requester
stopped in the middle of a deadline learns to route around the system, and
then it has neither the data nor their trust. So these tests spend most of
their effort on what must NOT trigger, and on the boundary where a single
off-by-one turns "we noticed something" into "you may not work".
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from dw_tender.adapters.preparation.rework_rules_loader import load_rework_support_rules
from dw_tender.application.preparation.rework import (
    ReworkEventView,
    ReworkSupportRules,
    SupportLevel,
    assess_rework,
)

pytestmark = pytest.mark.unit

RULES = load_rework_support_rules(
    Path(__file__).resolve().parents[5] / "configs" / "policies" / "dw01" / "rework_support_v1.yaml"
)

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def _event(
    days_ago: float,
    reason: str = "missing_pr_evidence",
    *,
    voided: bool = False,
) -> ReworkEventView:
    return ReworkEventView(
        event_id=uuid.uuid4(),
        occurred_at=NOW - timedelta(days=days_ago),
        reason_code=reason,
        checkpoint="intake",
        voided=voided,
    )


def _assess(events: list[ReworkEventView], rules: ReworkSupportRules = RULES):
    return assess_rework(events=events, now=NOW, rules=rules)


# --- the boundary ----------------------------------------------------------


def test_one_below_the_nudge_threshold_says_nothing() -> None:
    result = _assess([_event(1), _event(2)])
    assert result.level is SupportLevel.NONE
    assert result.nudge_count == 2


def test_exactly_the_nudge_threshold_nudges() -> None:
    """ "Reaches the threshold" includes hitting it exactly — >= not >."""
    result = _assess([_event(1), _event(2), _event(3)])
    assert result.level is SupportLevel.NUDGE


def test_one_above_the_nudge_threshold_still_only_nudges() -> None:
    result = _assess([_event(1), _event(2), _event(3), _event(4)])
    assert result.level is SupportLevel.NUDGE


def test_exactly_the_block_threshold_blocks() -> None:
    events = [_event(days) for days in (10, 12, 14, 16, 18)]
    result = _assess(events)
    assert result.level is SupportLevel.BLOCK
    assert result.block_count == 5


def test_one_below_the_block_threshold_does_not_block() -> None:
    events = [_event(days) for days in (10, 12, 14, 16)]
    assert _assess(events).level is not SupportLevel.BLOCK


# --- the two windows are independent ---------------------------------------


def test_events_outside_the_nudge_window_do_not_nudge() -> None:
    """Three returns spread over a month is not three returns in a week."""
    events = [_event(days) for days in (9, 15, 22)]
    result = _assess(events)
    assert result.nudge_count == 0
    assert result.block_count == 3
    assert result.level is SupportLevel.NONE


def test_events_outside_the_block_window_drop_out_entirely() -> None:
    events = [_event(days) for days in (31, 40, 60, 90, 120)]
    result = _assess(events)
    assert result.block_count == 0
    assert result.level is SupportLevel.NONE


def test_blocking_wins_when_both_windows_are_crossed() -> None:
    """Five in three days crosses both. The stricter level is the one in force."""
    events = [_event(days) for days in (0.5, 1, 1.5, 2, 2.5)]
    result = _assess(events)
    assert result.nudge_count == 5
    assert result.block_count == 5
    assert result.level is SupportLevel.BLOCK


def test_the_reported_window_and_count_follow_the_level_in_force() -> None:
    events = [_event(days) for days in (0.5, 1, 1.5, 2, 2.5)]
    result = _assess(events)
    assert result.window_days == RULES.block_window_days
    assert result.count == result.block_count


# --- what must not be counted ----------------------------------------------


def test_a_voided_event_is_not_counted() -> None:
    """An approver's mis-click stays on the record but leaves the tally."""
    events = [_event(1), _event(2), _event(3, voided=True)]
    result = _assess(events)
    assert result.nudge_count == 2
    assert result.level is SupportLevel.NONE


def test_voiding_can_pull_someone_back_from_blocked() -> None:
    events = [_event(days) for days in (10, 12, 14, 16)]
    events.append(_event(18, voided=True))
    assert _assess(events).level is not SupportLevel.BLOCK


def test_events_before_the_enabled_moment_are_not_counted() -> None:
    """No backfill: nobody gets blocked on day one for history nobody knew counted."""
    assert RULES.enabled_from is not None
    before = ReworkEventView(
        event_id=uuid.uuid4(),
        occurred_at=RULES.enabled_from - timedelta(days=1),
        reason_code="other",
    )
    # Sits inside the block window relative to a "now" just after switch-on.
    result = assess_rework(
        events=[before] * 9,
        now=RULES.enabled_from + timedelta(days=1),
        rules=RULES,
    )
    assert result.block_count == 0
    assert result.level is SupportLevel.NONE


def test_a_future_dated_event_is_not_counted() -> None:
    future = ReworkEventView(
        event_id=uuid.uuid4(),
        occurred_at=NOW + timedelta(days=1),
        reason_code="other",
    )
    assert _assess([future]).nudge_count == 0


# --- turning it off --------------------------------------------------------


def _disabled() -> ReworkSupportRules:
    return ReworkSupportRules(
        policy_version="1.0.0",
        enabled_from=None,
        nudge_window_days=7,
        nudge_threshold=0,
        block_window_days=30,
        block_threshold=0,
        explanation_min_chars=80,
        supporter_role="procurement_head",
        escalate_after_hours=48,
        general_guidance="…",
        reason_codes=RULES.reason_codes,
    )


def test_zero_thresholds_turn_the_feature_off_completely() -> None:
    events = [_event(day * 0.1) for day in range(50)]
    result = assess_rework(events=events, now=NOW, rules=_disabled())
    assert result.level is SupportLevel.NONE
    assert result.nudge_count == 0
    # Computed fine — there is simply nothing to say. Not an outage.
    assert result.available is True


# --- "nothing happened" must not look like "could not compute" -------------


def test_no_events_is_available_with_a_zero_count() -> None:
    result = _assess([])
    assert result.available is True
    assert result.nudge_count == 0


def test_unavailable_is_a_different_thing_from_a_clean_slate() -> None:
    from dw_tender.application.preparation.rework import ReworkAssessment

    outage = ReworkAssessment.unavailable(RULES)
    assert outage.available is False
    # Fails open: an outage never blocks anyone.
    assert outage.level is SupportLevel.NONE


# --- the top reason and its tie-break --------------------------------------


def test_the_most_frequent_reason_is_reported() -> None:
    events = [
        _event(1, "budget_mismatch"),
        _event(2, "budget_mismatch"),
        _event(3, "supplier_shortfall"),
    ]
    result = _assess(events)
    assert result.top_reason_code == "budget_mismatch"
    assert result.top_reason_label == "Ngân sách chưa khớp"


def test_a_tie_is_broken_by_catalogue_order_not_by_dict_order() -> None:
    """Insertion order must never decide what advice a person is shown."""
    events = [
        _event(1, "missing_documents"),
        _event(2, "budget_mismatch"),
        _event(3, "missing_pr_evidence"),
    ]
    result = _assess(events)
    # missing_pr_evidence is declared first in the rule pack.
    assert result.top_reason_code == "missing_pr_evidence"


def test_the_tie_break_is_stable_whatever_order_events_arrive_in() -> None:
    codes = ["missing_documents", "budget_mismatch", "missing_pr_evidence"]
    first = _assess([_event(i + 1, code) for i, code in enumerate(codes)])
    second = _assess([_event(i + 1, code) for i, code in enumerate(reversed(codes))])
    assert first.top_reason_code == second.top_reason_code


def test_the_top_reason_comes_from_the_window_that_is_in_force() -> None:
    """Blocked: advice must reflect the 30-day picture, not just this week."""
    events = [
        _event(1, "budget_mismatch"),
        _event(20, "supplier_shortfall"),
        _event(21, "supplier_shortfall"),
        _event(22, "supplier_shortfall"),
        _event(23, "supplier_shortfall"),
    ]
    result = _assess(events)
    assert result.level is SupportLevel.BLOCK
    assert result.top_reason_code == "supplier_shortfall"


def test_guidance_falls_back_to_the_general_text_for_an_unlisted_reason() -> None:
    events = [_event(1, "not_in_catalogue") for _ in range(3)]
    result = _assess(events)
    assert result.guidance == RULES.general_guidance
    assert result.guidance != ""


def test_no_level_means_no_advice_is_offered() -> None:
    result = _assess([_event(1)])
    assert result.top_reason_code is None
    assert result.guidance == ""


# --- determinism and the snapshot ------------------------------------------


def test_the_same_input_gives_the_same_verdict_twice() -> None:
    events = [_event(days) for days in (1, 2, 3, 12, 20)]
    assert _assess(events) == _assess(events)


def test_counted_event_ids_snapshot_the_window_in_force() -> None:
    """What the explanation gets tied to, captured at the moment it is asked for."""
    inside = [_event(days) for days in (1, 2, 3)]
    outside = [_event(29)]
    result = _assess(inside + outside)
    assert result.level is SupportLevel.NUDGE
    assert set(result.counted_event_ids) == {e.event_id for e in inside}


def test_the_policy_version_travels_with_the_verdict() -> None:
    assert _assess([_event(1)]).policy_version == RULES.policy_version
    assert RULES.policy_version != ""
