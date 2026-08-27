"""Every card that reaches Zalo must tell the reader what to do next.

Zalo has no buttons — a card there is words, and the reply hint is the entire
interaction surface. ``_reply_hint`` ends in ``return ""``, so an event type
nobody added a branch for produces a card with no call to action, no error,
and no way to notice until somebody stares at a dead-end message on their
phone. This test is the noticing.
"""

from __future__ import annotations

import uuid

import pytest

from dw_connectors.adapters.slack_approval_notifier import SlackApprovalMessage
from dw_connectors.adapters.zalo_approval_notifier import _reply_hint, render_text
from dw_tender.domain.preparation.notifications import IntakeNotificationType

pytestmark = pytest.mark.unit

# Cards that report an outcome and ask nothing of the reader. Everything else
# owes them a verb.
#
# intake.approved and intake.rejected are listed here as a statement of
# current behaviour, not of intent: both predate this test and both fall
# through to the empty default today. The rejection card in particular would
# read better with a next step, but changing it is a separate decision about
# an existing flow — this test exists to stop NEW event types from joining
# them by accident.
_NO_ACTION_EXPECTED = {
    IntakeNotificationType.RUN_PROGRESS,
    IntakeNotificationType.APPROVED,
    IntakeNotificationType.REJECTED,
}


def _message(event_type: str, *, checkpoint: str = "CP1") -> SlackApprovalMessage:
    return SlackApprovalMessage(
        message_id=uuid.uuid4(),
        recipient_slack_user_id="U1",
        event_type=event_type,
        case_id=uuid.uuid4(),
        case_title="Mua 30 máy trạm",
        web_url="https://example.test/case/c1",
        source_pr_ref="PR-1",
        owner_name="An",
        estimated_value_minor=0,
        currency="VND",
        comment="",
        heading="Tiêu đề",
        lines=("dòng",),
        buttons=(),
        checkpoint=checkpoint,
    )


@pytest.mark.parametrize(
    "event_type",
    [e for e in IntakeNotificationType if e not in _NO_ACTION_EXPECTED],
    ids=lambda e: e.value,
)
def test_every_actionable_event_type_has_a_reply_hint(event_type) -> None:
    hint = _reply_hint(_message(event_type.value))
    assert hint.strip(), f"{event_type.value} falls through to the empty default"


@pytest.mark.parametrize(
    "event_type",
    [
        IntakeNotificationType.REWORK_SUPPORT_OFFERED,
        IntakeNotificationType.REWORK_SUPPORT_REQUIRED,
        IntakeNotificationType.REWORK_EXPLANATION_ESCALATED,
    ],
    ids=lambda e: e.value,
)
def test_rework_cards_never_accuse_the_reader(event_type) -> None:
    text = render_text(_message(event_type.value)).lower()
    for accusation in ("vi phạm", "sai phạm", "lách", "chia nhỏ"):
        assert accusation not in text


def test_the_offer_card_does_not_demand_anything() -> None:
    """Soft means soft: at the nudge level nothing is owed and nothing is due."""
    hint = _reply_hint(_message(IntakeNotificationType.REWORK_SUPPORT_OFFERED.value))
    assert "cần hỗ trợ" in hint.lower()


def test_an_unknown_event_type_still_falls_through() -> None:
    """Documents the trap this test exists to catch."""
    assert _reply_hint(_message("something.new")) == ""
