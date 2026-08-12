"""Close the bid register when its moment arrives, not when a count is reached.

Real procurement opens at the stated time with whatever has been received;
waiting for a quorum is what creates the window in which envelopes can leak or
be swapped. DW01 already auto-requested CP4 once enough bids landed — this is
the other half: a case whose closing moment has passed goes to CP4 regardless,
and says plainly when fewer bids arrived than the method requires, because that
is a decision for the person, not something to hide.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from dw_kernel.errors import DWError
from dw_kernel.ids import TenantId
from dw_kernel.ports import UtcClock
from dw_platform.application.access_context import AccessContext
from dw_tender.application.preparation.handlers import RequestCp4Handler
from dw_tender.application.preparation.ports import PreparationUnitOfWorkFactory
from dw_tender.application.preparation.rules import ProcurementRules


@dataclass(frozen=True, slots=True)
class ClosingReport:
    closed: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()


@dataclass
class BidClosingScanner:
    """Polls for cases past their closing moment and sends them to CP4."""

    uow_factory: PreparationUnitOfWorkFactory
    request_cp4: RequestCp4Handler
    rules: ProcurementRules
    clock: UtcClock
    # Cases already pushed to CP4 by this process — the handler is idempotent
    # on the notification, this just avoids re-querying work already done.
    _seen: set[uuid.UUID] = field(default_factory=set)

    async def poll_once(self, context: AccessContext) -> ClosingReport:
        now = self.clock.now()
        async with self.uow_factory(TenantId(context.tenant_id)) as uow:
            due = await uow.cases.list_due_for_closing(now)
        closed: list[str] = []
        skipped: list[str] = []
        for case in due:
            if case.id.value in self._seen:
                continue
            try:
                count = await self.request_cp4.handle(case.id.value, context)
            except DWError as exc:
                # No bids at all is the common one: nothing to open, and the
                # case needs a human to extend or cancel — not a silent retry.
                skipped.append(f"{case.title}: {exc}")
                self._seen.add(case.id.value)
                continue
            minimum = self.rules.select_method(case.estimated_value_minor).min_suppliers
            note = "" if count >= minimum else f" (chỉ {count}/{minimum} nhà cung cấp tối thiểu)"
            closed.append(f"{case.title}: đã tới hạn, trình CP4 với {count} hồ sơ{note}")
            self._seen.add(case.id.value)
        return ClosingReport(closed=tuple(closed), skipped=tuple(skipped))
