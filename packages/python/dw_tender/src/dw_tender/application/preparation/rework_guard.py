"""The gate that can stop someone from filing new work — and its safety catch.

Everything here is shaped by one asymmetry. Missing a pattern costs a few more
rounds of corrections. Blocking someone wrongly costs their afternoon, their
deadline, and their willingness to use the system honestly next time. So the
gate is built to fail towards letting people work:

* ``assess`` never raises. A database that is down, a rule pack that failed to
  load, a query that timed out — all of them come back as "could not compute",
  which blocks nobody and is distinguishable in the logs from a clean slate.
* Only two actions are gated: opening a new case, and submitting one for
  decision. Editing and saving work already in progress stays open, because
  telling someone to fix their paperwork while refusing to let them fix it is
  not a support mechanism, it is a trap.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, timedelta

from dw_kernel.errors import ConflictError
from dw_kernel.ids import TenantId, UserId
from dw_kernel.ports import UtcClock
from dw_platform.application.access_context import AccessContext
from dw_tender.application.preparation.ports import PreparationUnitOfWorkFactory
from dw_tender.application.preparation.rework import (
    ReworkAssessment,
    ReworkEventView,
    ReworkSupportRules,
    SupportLevel,
    assess_rework,
)
from dw_tender.application.preparation.rework_wording import blocked_message

logger = logging.getLogger(__name__)


@dataclass
class ReworkGuard:
    uow_factory: PreparationUnitOfWorkFactory
    rules: ReworkSupportRules
    clock: UtcClock

    async def assess(self, context: AccessContext) -> ReworkAssessment:
        """Where this person stands. Never raises — see the module docstring."""
        if not self.rules.is_enabled():
            return ReworkAssessment.disabled(self.rules)
        try:
            return await self._assess(context)
        except Exception:
            logger.warning(
                "rework support assessment unavailable; failing open",
                extra={"tenant_id": str(context.tenant_id)},
                exc_info=True,
            )
            return ReworkAssessment.unavailable(self.rules)

    async def _assess(self, context: AccessContext) -> ReworkAssessment:
        now = self.clock.now().astimezone(UTC)
        # One read covering the longer of the two windows; the pure core slices
        # it into both. Asking twice would be two round trips for one answer,
        # and the two answers could straddle a write.
        span = max(self.rules.nudge_window_days, self.rules.block_window_days)
        since = now - timedelta(days=span)
        creator = UserId(context.principal_id)

        async with self.uow_factory(TenantId(context.tenant_id)) as uow:
            events = await uow.rework_events.list_for_creator(creator, since=since)
            assessment = assess_rework(
                events=[
                    ReworkEventView(
                        event_id=event.id,
                        occurred_at=event.occurred_at,
                        reason_code=event.reason_code,
                        checkpoint=event.checkpoint.value,
                        voided=event.voided,
                    )
                    for event in events
                ],
                now=now,
                rules=self.rules,
            )
            if assessment.level is not SupportLevel.BLOCK:
                return assessment
            # A block is lifted by a person, not by a counter. Old events
            # ageing out of the window must not quietly release someone —
            # somebody has to have read the explanation and said so.
            if await uow.explanations.has_approved_since(creator, since=since):
                return ReworkAssessment(
                    available=True,
                    level=SupportLevel.NUDGE if assessment.nudge_count else SupportLevel.NONE,
                    nudge_count=assessment.nudge_count,
                    block_count=assessment.block_count,
                    nudge_window_days=assessment.nudge_window_days,
                    nudge_threshold=assessment.nudge_threshold,
                    block_window_days=assessment.block_window_days,
                    block_threshold=assessment.block_threshold,
                    policy_version=assessment.policy_version,
                    top_reason_code=assessment.top_reason_code,
                    top_reason_label=assessment.top_reason_label,
                    guidance=assessment.guidance,
                    counted_event_ids=assessment.counted_event_ids,
                )
            return assessment

    async def require_not_blocked(self, context: AccessContext) -> None:
        """Refuse the action if this person is waiting on an explanation.

        The refusal carries the count, the window and the way out — a "no"
        with no next step is where people start working around the system.
        """
        assessment = await self.assess(context)
        if assessment.level is not SupportLevel.BLOCK:
            return
        raise ConflictError(
            blocked_message(assessment),
            details={
                "reason": "rework_support_required",
                "block_count": assessment.block_count,
                "block_window_days": assessment.block_window_days,
                "policy_version": assessment.policy_version,
            },
        )
