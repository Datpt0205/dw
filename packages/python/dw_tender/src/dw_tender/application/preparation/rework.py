"""Has this person's paperwork been coming back a lot lately?

Not a performance metric, and the wording must never suggest otherwise. A
requester whose cases get returned three times in a week is usually someone
who has not been shown the template, or whose department hands them an
incomplete brief. What the rule pack asks for is a conversation: notice the
pattern early, ask what is getting in the way, route help.

Which is why a false alarm costs more than a miss. Blocking someone wrongly in
the middle of a deadline teaches them to work around the system, and then it
loses both the data and the goodwill. The thresholds live in the rule pack so
procurement can move them without a deploy.

Pure: counting and thresholds run on what the caller supplies, including the
clock. No I/O, no ``datetime.now()`` — same events plus same reference moment
always give the same verdict, which is what makes a blocking decision
defensible after the fact.
"""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum


class SupportLevel(StrEnum):
    """How far the support ladder has been climbed for one person."""

    NONE = "none"
    # Show a card, offer the form, get out of the way.
    NUDGE = "nudge"
    # New cases and checkpoint submissions wait for a written explanation.
    BLOCK = "block"


@dataclass(frozen=True, slots=True)
class ReworkReason:
    """One entry of the closed catalogue an approver picks from."""

    code: str
    label: str
    guidance: str


@dataclass(frozen=True)
class ReworkSupportRules:
    """The versioned rule pack, already parsed.

    ``reason_codes`` keeps declaration order on purpose: it is how ties are
    broken when two reasons occur equally often. Iterating a dict and taking
    the first max would make the card's advice depend on insertion order —
    reproducible in one process and not the next.
    """

    policy_version: str
    enabled_from: datetime | None
    nudge_window_days: int
    nudge_threshold: int
    block_window_days: int
    block_threshold: int
    explanation_min_chars: int
    supporter_role: str
    escalate_after_hours: int
    general_guidance: str
    reason_codes: tuple[ReworkReason, ...] = ()

    def is_enabled(self) -> bool:
        """Both thresholds at zero turns the whole feature off (no card, no block)."""
        return self.nudge_threshold > 0 or self.block_threshold > 0

    def is_known(self, code: str) -> bool:
        return any(reason.code == code for reason in self.reason_codes)

    def reason(self, code: str | None) -> ReworkReason | None:
        if not code:
            return None
        for reason in self.reason_codes:
            if reason.code == code:
                return reason
        return None

    def label_for(self, code: str | None) -> str:
        reason = self.reason(code)
        return reason.label if reason else ""

    def guidance_for(self, code: str | None) -> str:
        """Advice for this reason, falling back to the general text.

        Never returns empty when the rule pack has a general guidance: an
        support card with a blank advice slot is worse than no card at all.
        """
        reason = self.reason(code)
        if reason is not None and reason.guidance.strip():
            return reason.guidance.strip()
        return self.general_guidance.strip()

    def rank_of(self, code: str) -> int:
        """Position in the catalogue — the deterministic tie-break key."""
        for index, reason in enumerate(self.reason_codes):
            if reason.code == code:
                return index
        return len(self.reason_codes)


@dataclass(frozen=True, slots=True)
class ReworkEventView:
    """One returned case, reduced to what counting actually needs.

    Deliberately not the persisted entity: the pure core must stay callable
    from a test that has never opened a database.
    """

    event_id: uuid.UUID
    occurred_at: datetime
    reason_code: str
    checkpoint: str = ""
    voided: bool = False


@dataclass(frozen=True)
class ReworkAssessment:
    """What the support ladder says about one person right now.

    ``available`` is the whole point of this being a separate field. "No cases
    came back" and "the count could not be computed" must never look alike to
    the caller: the first is good news, the second is an outage, and a
    mechanism that blocks people has to tell them apart before it decides
    anything.
    """

    available: bool
    level: SupportLevel
    nudge_count: int
    block_count: int
    nudge_window_days: int
    nudge_threshold: int
    block_window_days: int
    block_threshold: int
    policy_version: str
    top_reason_code: str | None = None
    top_reason_label: str = ""
    guidance: str = ""
    counted_event_ids: tuple[uuid.UUID, ...] = ()

    @property
    def blocked(self) -> bool:
        return self.level is SupportLevel.BLOCK

    @property
    def window_days(self) -> int:
        """The window that produced the level currently in force."""
        return self.block_window_days if self.blocked else self.nudge_window_days

    @property
    def count(self) -> int:
        """The count that produced the level currently in force."""
        return self.block_count if self.blocked else self.nudge_count

    @classmethod
    def unavailable(cls, rules: ReworkSupportRules | None = None) -> ReworkAssessment:
        """Could not compute — fail open, and say so.

        Level is NONE so nothing blocks, but ``available`` stays False so the
        caller can log an outage rather than report a clean slate.
        """
        return cls(
            available=False,
            level=SupportLevel.NONE,
            nudge_count=0,
            block_count=0,
            nudge_window_days=rules.nudge_window_days if rules else 0,
            nudge_threshold=rules.nudge_threshold if rules else 0,
            block_window_days=rules.block_window_days if rules else 0,
            block_threshold=rules.block_threshold if rules else 0,
            policy_version=rules.policy_version if rules else "",
        )

    @classmethod
    def disabled(cls, rules: ReworkSupportRules) -> ReworkAssessment:
        """Turned off in the rule pack. Computed fine; there is just nothing to say."""
        return cls(
            available=True,
            level=SupportLevel.NONE,
            nudge_count=0,
            block_count=0,
            nudge_window_days=rules.nudge_window_days,
            nudge_threshold=rules.nudge_threshold,
            block_window_days=rules.block_window_days,
            block_threshold=rules.block_threshold,
            policy_version=rules.policy_version,
        )


def _counts_within(
    events: tuple[ReworkEventView, ...], *, now: datetime, days: int
) -> tuple[ReworkEventView, ...]:
    """Events inside a window measured backwards from ``now``.

    Rolling, not calendar: "3 in 7 days" means the last 7x24 hours, so the
    verdict does not lurch every Monday morning.
    """
    if days <= 0:
        return ()
    cutoff = now - timedelta(days=days)
    return tuple(event for event in events if cutoff <= event.occurred_at <= now)


def _top_reason(events: tuple[ReworkEventView, ...], rules: ReworkSupportRules) -> str | None:
    """The most frequent reason, ties broken by catalogue order."""
    if not events:
        return None
    tally = Counter(event.reason_code for event in events if event.reason_code)
    if not tally:
        return None
    highest = max(tally.values())
    tied = [code for code, count in tally.items() if count == highest]
    return min(tied, key=lambda code: (rules.rank_of(code), code))


def assess_rework(
    *,
    events: list[ReworkEventView],
    now: datetime,
    rules: ReworkSupportRules,
) -> ReworkAssessment:
    """Where on the support ladder this person's recent history puts them.

    Order matters twice over. Voided events drop out before anything is
    counted, because a mis-click must not sit in the tally forever. And the
    blocking window is tested before the nudging one, so that crossing both at
    once lands on the stricter of the two rather than on whichever branch
    happened to be written first.
    """
    if not rules.is_enabled():
        return ReworkAssessment.disabled(rules)

    considered = tuple(
        event
        for event in events
        # A mis-click, marked as such by the approver. The row survives for the
        # audit trail; the count moves on.
        if not event.voided
        # Nothing before the day the feature was switched on. Counting history
        # would block people on the first morning for returns that happened
        # when nobody knew this mechanism existed.
        and (rules.enabled_from is None or event.occurred_at >= rules.enabled_from)
    )

    nudge_events = _counts_within(considered, now=now, days=rules.nudge_window_days)
    block_events = _counts_within(considered, now=now, days=rules.block_window_days)
    nudge_count = len(nudge_events)
    block_count = len(block_events)

    # ">=" on purpose: the requirement says "reaches the threshold", so hitting
    # it exactly counts. Blocking is checked first — when both fire, the
    # stricter level wins.
    if rules.block_threshold > 0 and block_count >= rules.block_threshold:
        level = SupportLevel.BLOCK
        window_events = block_events
    elif rules.nudge_threshold > 0 and nudge_count >= rules.nudge_threshold:
        level = SupportLevel.NUDGE
        window_events = nudge_events
    else:
        level = SupportLevel.NONE
        window_events = nudge_events

    top_code = _top_reason(window_events, rules) if level is not SupportLevel.NONE else None
    return ReworkAssessment(
        available=True,
        level=level,
        nudge_count=nudge_count,
        block_count=block_count,
        nudge_window_days=rules.nudge_window_days,
        nudge_threshold=rules.nudge_threshold,
        block_window_days=rules.block_window_days,
        block_threshold=rules.block_threshold,
        policy_version=rules.policy_version,
        top_reason_code=top_code,
        top_reason_label=rules.label_for(top_code),
        guidance=rules.guidance_for(top_code) if level is not SupportLevel.NONE else "",
        # Snapshot of exactly what pushed this person over, so an explanation
        # submitted now can be tied to the events that prompted it — not to
        # whatever the window happens to hold when someone reopens it later.
        counted_event_ids=tuple(event.event_id for event in window_events),
    )
