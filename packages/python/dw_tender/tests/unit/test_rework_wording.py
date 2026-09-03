"""The phrasing is a requirement, so it gets tested like one.

This is the same standard ``test_repeat_purchase.py`` already holds, applied
to a feature that goes further: this one can stop someone from working. A
mechanism with that much reach has to be certain it never tells a colleague
they are suspected of something.

Every string-producing function, at every level, against every reason in the
shipped catalogue. Cheap to run, and it fails the moment someone writes a
sentence in a hurry.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from dw_tender.adapters.preparation.rework_rules_loader import load_rework_support_rules
from dw_tender.application.preparation.rework import (
    ReworkEventView,
    SupportLevel,
    assess_rework,
)
from dw_tender.application.preparation.rework_wording import (
    FORBIDDEN,
    blocked_message,
    escalation_lines,
    explanation_prompt,
    support_headline,
    support_lines,
    supporter_lines,
)

pytestmark = pytest.mark.unit

RULES = load_rework_support_rules(
    Path(__file__).resolve().parents[5] / "configs" / "policies" / "dw01" / "rework_support_v1.yaml"
)

NOW = datetime(2026, 9, 20, tzinfo=UTC)


def _assessment(count: int, reason: str, *, spread_days: float = 1.0):
    events = [
        ReworkEventView(
            event_id=uuid.uuid4(),
            occurred_at=NOW - timedelta(days=(i + 1) * spread_days),
            reason_code=reason,
        )
        for i in range(count)
    ]
    return assess_rework(events=events, now=NOW, rules=RULES)


def _every_rendered_string(assessment) -> list[str]:
    return [
        support_headline(assessment),
        *support_lines(assessment),
        explanation_prompt(assessment),
        blocked_message(assessment),
        *supporter_lines(assessment, creator_label="Nguyễn Văn A"),
        *escalation_lines(assessment, creator_label="Nguyễn Văn A"),
    ]


ALL_REASONS = [reason.code for reason in RULES.reason_codes]


@pytest.mark.parametrize("reason", ALL_REASONS)
@pytest.mark.parametrize("count,spread", [(3, 1.0), (5, 1.0), (6, 4.0)])
def test_no_rendered_string_accuses_anyone(reason: str, count: int, spread: float) -> None:
    assessment = _assessment(count, reason, spread_days=spread)
    for text in _every_rendered_string(assessment):
        lowered = text.lower()
        for accusation in FORBIDDEN:
            assert accusation not in lowered, f"{accusation!r} in {text!r}"


def test_the_forbidden_list_is_the_one_the_older_rule_already_holds() -> None:
    """Same standard as repeat_purchase, not a new one invented here."""
    assert set(FORBIDDEN) >= {"vi phạm", "sai phạm", "lách", "chia nhỏ"}


# --- the card must actually say something useful ---------------------------


def test_a_nudge_card_names_the_count_the_window_and_a_next_step() -> None:
    assessment = _assessment(3, "budget_mismatch")
    assert assessment.level is SupportLevel.NUDGE
    headline = support_headline(assessment)
    assert "3" in headline
    assert str(RULES.nudge_window_days) in headline
    lines = support_lines(assessment)
    assert any(RULES.label_for("budget_mismatch") in line for line in lines)
    assert any(line.strip() for line in lines)


def test_a_nudge_card_says_work_carries_on() -> None:
    """Soft means soft — the card must not read like a stop sign."""
    lines = " ".join(support_lines(_assessment(3, "other")))
    assert "bình thường" in lines


def test_a_block_card_says_exactly_how_to_get_moving_again() -> None:
    assessment = _assessment(5, "supplier_shortfall")
    assert assessment.level is SupportLevel.BLOCK
    text = " ".join([*support_lines(assessment), blocked_message(assessment)])
    assert "mô tả" in text
    # A refusal without a way forward is where people start working around it.
    assert "hồ sơ mới" in text


def test_the_refusal_says_work_in_progress_is_untouched() -> None:
    """RF-42: being blocked must not read as "you may not fix anything"."""
    assert "sửa" in blocked_message(_assessment(5, "other"))


def test_no_card_is_rendered_when_nothing_crossed_a_threshold() -> None:
    quiet = _assessment(1, "other")
    assert quiet.level is SupportLevel.NONE
    assert support_headline(quiet) == ""
    assert support_lines(quiet) == []


def test_advice_is_never_blank_even_for_a_reason_with_no_guidance() -> None:
    assessment = _assessment(3, "not_in_catalogue")
    assert any(line.strip() for line in support_lines(assessment))


def test_the_supporter_card_asks_for_help_not_for_an_investigation() -> None:
    lines = " ".join(supporter_lines(_assessment(5, "criteria_issue"), creator_label="An"))
    assert "hỗ trợ" in lines or "gỡ vướng" in lines


def test_the_escalation_card_is_about_the_queue_not_the_person() -> None:
    lines = " ".join(escalation_lines(_assessment(5, "other"), creator_label="An"))
    assert "chưa có ai xem" in lines
