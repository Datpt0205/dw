"""How many new requests one person may open in a period, and what happens then.

The counting is pure and lives here; reading the database and refusing the
action live in ``intake_quota_guard``. That split is what makes the period
boundary testable without a clock or a connection.

Two decisions are worth stating because they are not obvious from the code.

**The period is a calendar month, not a rolling window.** Rework support counts
on a rolling window because it measures a pattern the system invented. A quota
enforces a sentence somebody wrote in a company regulation, and running it on a
rolling window would enforce a different rule than the written one. It also has
to be a period a person can count for themselves — everybody knows the month
resets on the 1st; nobody can feel where a rolling 30 days begins.

**A case someone else closed does not hold a slot.** Rejected and failed cases
return their slot to the requester, so the count can go *down*. That is
deliberate: the quota measures what you are occupying, not how many times you
typed. It also keeps this mechanism from punishing the same event twice — being
turned down repeatedly is what rework support is for, and a person whose work
keeps coming back would otherwise be hit by both.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class IntakeQuotaRules:
    """The versioned rule pack, already parsed."""

    policy_version: str
    source: str
    enabled_from: datetime | None
    timezone: str
    threshold: int
    burst_window_days: int
    burst_threshold: int
    count_closed_unsuccessful: bool
    explanation_min_chars: int
    approver_role: str
    escalate_after_hours: int
    guidance: str

    def is_enabled(self) -> bool:
        """Both thresholds at zero turns the whole thing off — no card, no block."""
        return self.threshold > 0 or self.burst_threshold > 0

    def zone(self) -> tzinfo:
        """The clock the period boundary is cut on.

        Falls back to plain UTC rather than raising: a mistyped zone must not
        take the intake path down, and the loader has already rejected the
        obvious cases at startup. The fallback is ``datetime.UTC`` and not
        ``ZoneInfo("UTC")`` because a host with no tz database would fail on
        that too — which is exactly the situation the fallback is for.
        """
        try:
            return ZoneInfo(self.timezone)
        except Exception:  # pragma: no cover - loader validates at startup
            return UTC


@dataclass(frozen=True, slots=True)
class OpenedCase:
    """One case this person opened, reduced to what counting needs."""

    case_id: object
    opened_at: datetime
    closed_unsuccessfully: bool


@dataclass(frozen=True)
class QuotaAssessment:
    """Where one person stands against the quota, and why."""

    available: bool
    blocked: bool
    used: int
    threshold: int
    period_label: str
    burst_used: int
    burst_threshold: int
    burst_window_days: int
    policy_version: str
    guidance: str
    counted_case_ids: tuple[str, ...] = ()

    @property
    def remaining(self) -> int:
        return max(self.threshold - self.used, 0)

    @classmethod
    def unavailable(cls, rules: IntakeQuotaRules | None = None) -> QuotaAssessment:
        """Could not be computed — blocks nobody, and says so in the logs.

        Distinct from a clean slate on purpose: ``available=False`` with a zero
        count reads as "we do not know", which is what an operator needs to see
        when the database was down.
        """
        return cls(
            available=False,
            blocked=False,
            used=0,
            threshold=rules.threshold if rules else 0,
            period_label="",
            burst_used=0,
            burst_threshold=rules.burst_threshold if rules else 0,
            burst_window_days=rules.burst_window_days if rules else 0,
            policy_version=rules.policy_version if rules else "",
            guidance="",
        )

    @classmethod
    def disabled(cls, rules: IntakeQuotaRules) -> QuotaAssessment:
        return cls(
            available=True,
            blocked=False,
            used=0,
            threshold=rules.threshold,
            period_label="",
            burst_used=0,
            burst_threshold=rules.burst_threshold,
            burst_window_days=rules.burst_window_days,
            policy_version=rules.policy_version,
            guidance="",
        )


def period_bounds(now: datetime, rules: IntakeQuotaRules) -> tuple[datetime, datetime, str]:
    """First and last instant of the calendar month containing ``now``, in UTC.

    Cut in the rule pack's timezone and converted back, because the system
    stores UTC: a case opened 01/10 00:30 in Vietnam is 30/09 17:30 UTC, and
    slicing on UTC would file it under the previous month — blocking somebody
    on the first night of a period they have not started using.
    """
    zone = rules.zone()
    local = now.astimezone(zone)
    start_local = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    next_month = (start_local.replace(day=28) + timedelta(days=4)).replace(day=1)
    return (
        start_local.astimezone(UTC),
        next_month.astimezone(UTC),
        f"{start_local:%m/%Y}",
    )


def assess_quota(
    *,
    cases: list[OpenedCase],
    now: datetime,
    rules: IntakeQuotaRules,
) -> QuotaAssessment:
    """Count what is occupying a slot, and say whether that is over the line."""
    if not rules.is_enabled():
        return QuotaAssessment.disabled(rules)

    start, _end, label = period_bounds(now, rules)
    floor = rules.enabled_from
    burst_since = now - timedelta(days=rules.burst_window_days)

    def holds_a_slot(case: OpenedCase) -> bool:
        if floor is not None and case.opened_at < floor:
            return False
        return rules.count_closed_unsuccessful or not case.closed_unsuccessfully

    in_period = [c for c in cases if holds_a_slot(c) and c.opened_at >= start]
    in_burst = [c for c in cases if holds_a_slot(c) and c.opened_at >= burst_since]

    used = len(in_period)
    burst_used = len(in_burst)
    over_period = rules.threshold > 0 and used >= rules.threshold
    over_burst = rules.burst_threshold > 0 and burst_used >= rules.burst_threshold
    counted = in_period if over_period else in_burst

    return QuotaAssessment(
        available=True,
        blocked=over_period or over_burst,
        used=used,
        threshold=rules.threshold,
        period_label=label,
        burst_used=burst_used,
        burst_threshold=rules.burst_threshold,
        burst_window_days=rules.burst_window_days,
        policy_version=rules.policy_version,
        guidance=rules.guidance if (over_period or over_burst) else "",
        counted_case_ids=tuple(str(c.case_id) for c in counted),
    )


def blocked_message(assessment: QuotaAssessment) -> str:
    """The refusal, with the count, the period and the way out.

    A "no" with no next step is where people start working around the system,
    so the last line always says what unblocks it.
    """
    if assessment.burst_threshold > 0 and assessment.burst_used >= assessment.burst_threshold:
        headline = (
            f"⚠️ Bạn đã mở {assessment.burst_used} yêu cầu trong "
            f"{assessment.burst_window_days} ngày qua."
        )
    else:
        headline = (
            f"⚠️ Bạn đã dùng {assessment.used}/{assessment.threshold} suất "
            f"yêu cầu mua sắm của kỳ {assessment.period_label}."
        )
    lines = [
        headline,
        "",
        "Mình chưa mở yêu cầu mới được — cần một bản giải trình ngắn gửi bộ phận "
        "mua sắm duyệt trước.",
    ]
    if assessment.guidance:
        lines += ["", assessment.guidance]
    lines += ["", "Bạn nhắn cho mình lý do cần thêm đợt này, mình chuyển đi ngay."]
    return "\n".join(lines)
