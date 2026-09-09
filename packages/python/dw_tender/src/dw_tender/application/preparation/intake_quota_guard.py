"""The gate that stops someone opening more requests than their quota allows.

Shaped like ``ReworkGuard`` and for the same reason: ``assess`` never raises.
A database that is down or a rule pack that failed to load comes back as "could
not compute", which blocks nobody and reads differently in the logs from a
clean slate. Letting one extra request through costs a late justification;
refusing someone wrongly costs their afternoon and their willingness to use the
system honestly next time.

Only opening a NEW case is gated. Work already in progress stays open — telling
someone their quota is full while also refusing to let them finish what they
started would be a trap, not a control.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, timedelta

from dw_kernel.errors import ConflictError
from dw_kernel.ids import TenantId, UserId
from dw_kernel.ports import UtcClock
from dw_platform.application.access_context import AccessContext
from dw_tender.application.preparation.intake_quota import (
    IntakeQuotaRules,
    OpenedCase,
    QuotaAssessment,
    assess_quota,
    blocked_message,
    period_bounds,
)
from dw_tender.application.preparation.ports import PreparationUnitOfWorkFactory

logger = logging.getLogger(__name__)


@dataclass
class IntakeQuotaGuard:
    uow_factory: PreparationUnitOfWorkFactory
    rules: IntakeQuotaRules
    clock: UtcClock

    async def assess(self, context: AccessContext) -> QuotaAssessment:
        """Where this person stands. Never raises — see the module docstring."""
        if not self.rules.is_enabled():
            return QuotaAssessment.disabled(self.rules)
        try:
            return await self._assess(context)
        except Exception:
            logger.warning(
                "intake quota assessment unavailable; failing open",
                extra={"tenant_id": str(context.tenant_id)},
                exc_info=True,
            )
            return QuotaAssessment.unavailable(self.rules)

    async def _assess(self, context: AccessContext) -> QuotaAssessment:
        now = self.clock.now().astimezone(UTC)
        # One read covering whichever of the two spans reaches further back;
        # the pure core slices it into both. Two queries would be two round
        # trips for one answer, and they could straddle a write.
        start, _end, _label = period_bounds(now, self.rules)
        burst_since = now - timedelta(days=self.rules.burst_window_days)
        since = min(start, burst_since)
        creator = UserId(context.principal_id)

        async with self.uow_factory(TenantId(context.tenant_id)) as uow:
            opened = await uow.cases.list_opened_by(creator, since=since)
            assessment = assess_quota(
                cases=[
                    OpenedCase(
                        case_id=case.case_id,
                        opened_at=case.opened_at,
                        closed_unsuccessfully=case.state.is_closed_unsuccessfully,
                    )
                    for case in opened
                ],
                now=now,
                rules=self.rules,
            )
            if not assessment.blocked:
                return assessment
            # A block is lifted by a person, not by the calendar. Somebody has
            # to have read the justification and said yes.
            if await uow.explanations.has_approved_since(creator, since=since, kind="intake_quota"):
                return QuotaAssessment(
                    available=True,
                    blocked=False,
                    used=assessment.used,
                    threshold=assessment.threshold,
                    period_label=assessment.period_label,
                    burst_used=assessment.burst_used,
                    burst_threshold=assessment.burst_threshold,
                    burst_window_days=assessment.burst_window_days,
                    policy_version=assessment.policy_version,
                    guidance="",
                    counted_case_ids=assessment.counted_case_ids,
                )
            return assessment

    async def require_not_blocked(self, context: AccessContext) -> None:
        """Refuse to open a new case when the quota is used up and unexplained."""
        assessment = await self.assess(context)
        if not assessment.blocked:
            return
        raise ConflictError(
            blocked_message(assessment),
            details={
                "reason": "intake_quota_explanation_required",
                "used": assessment.used,
                "threshold": assessment.threshold,
                "period": assessment.period_label,
                "policy_version": assessment.policy_version,
            },
        )
