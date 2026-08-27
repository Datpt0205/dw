"""Re-read the law under packages that are still waiting to be signed.

A procurement package cites an article, derives a deadline from it, and then
sits — for days, sometimes weeks — while people decide. If the article changes
in that gap, nothing notices: the approval card still describes a window taken
from a provision that no longer says what it said. The requester finds out when
a bidder complains.

So the cases in that gap are re-read on a schedule against the same live sources
that drafted them, using the same evidence rules. What changed is reported and
nothing else happens. The approval keeps standing, because a search result is
not grounds to tear up work already under way, and an alert a person can
evaluate is worth more than an automatic action they have to undo. When a change
does matter, the person has ``amend`` — which withdraws the checkpoint properly
and re-runs every gate.

Alerts are keyed by what the law now says, so a change is reported once no
matter how often the sweep runs. A watcher that cried every six hours would be
muted within a day, and then the one that mattered would go unread too.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Protocol

from dw_kernel.errors import DWError
from dw_kernel.ids import TenantId, UserId
from dw_kernel.ports import IdGenerator, UtcClock
from dw_platform.application.access_context import AccessContext
from dw_tender.application.preparation.ports import PreparationUnitOfWorkFactory
from dw_tender.application.preparation.rules import ProcurementRules
from dw_tender.domain.preparation.entities import (
    ArtifactStatus,
    ArtifactType,
    CaseState,
    PreparationCase,
)
from dw_tender.domain.preparation.notifications import (
    IntakeNotificationJob,
    IntakeNotificationType,
)
from dw_tender.domain.value_objects.ids import PreparationCaseId

# Which checkpoint's approver is the one to tell. Before CP1 is decided that is
# CP1's holder; afterwards the package belongs to whoever signs CP2. Both come
# from the versioned approval matrix by package value — the same path the
# approval cards themselves use, so the alert lands with the person actually
# holding the decision rather than a role guessed here.
_CHECKPOINT_FOR_STATE = {
    CaseState.APPROACH_READY: "CP1",
    CaseState.CP1_PENDING: "CP1",
}


@dataclass(frozen=True, slots=True)
class LegalPosition:
    """What the sources said about the bid-preparation window, at some moment."""

    min_bid_preparation_days: int | None
    article_ref: str
    source_quote: str

    @classmethod
    def from_artifact(cls, content: dict[str, object]) -> LegalPosition | None:
        constraints = content.get("legal_constraints")
        if not isinstance(constraints, dict):
            return None
        extracted = constraints.get("extracted")
        if not isinstance(extracted, dict):
            # Drafted with no verified constraint: the deterministic default
            # applied, so there is no cited position to compare against.
            return None
        days = extracted.get("min_bid_preparation_days")
        return cls(
            min_bid_preparation_days=int(days) if isinstance(days, int) else None,
            article_ref=str(extracted.get("article_ref") or ""),
            source_quote=str(extracted.get("source_quote") or ""),
        )

    def differs_from(self, other: LegalPosition) -> bool:
        """Same number under the same article is the same position.

        Wording is deliberately not compared: sources reformat, and a diff that
        fires on whitespace teaches people to ignore it.
        """
        return (
            self.min_bid_preparation_days != other.min_bid_preparation_days
            or self.article_ref.strip().casefold() != other.article_ref.strip().casefold()
        )

    @property
    def fingerprint(self) -> str:
        raw = f"{self.min_bid_preparation_days}|{self.article_ref.strip().casefold()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class LawWatchReport:
    checked: tuple[str, ...] = ()
    changed: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()


class LegalPositionReaderPort(Protocol):
    """Reads what the sources say about a case's window RIGHT NOW.

    Behind this sits retrieval plus a model extraction. Neither belongs in
    application logic, and keeping it a port is what lets the sweep be tested
    without a network or a model.
    """

    async def __call__(
        self, case: PreparationCase, context: AccessContext
    ) -> LegalPosition | None: ...


@dataclass
class LawChangeScanner:
    """Sweeps waiting cases and reports when their cited law has moved.

    ``read_current`` is injected rather than built here: re-reading the law is
    retrieval plus a model extraction, and this module is application logic that
    must not know about either.
    """

    uow_factory: PreparationUnitOfWorkFactory
    read_current: LegalPositionReaderPort
    rules: ProcurementRules
    clock: UtcClock
    id_generator: IdGenerator
    limit: int = 20
    # Alerts already queued this process-lifetime, keyed case+fingerprint. The
    # idempotency key on the job is the durable guard; this just avoids the work.
    _announced: set[str] = field(default_factory=set)

    async def poll_once(self, context: AccessContext) -> LawWatchReport:
        async with self.uow_factory(TenantId(context.tenant_id)) as uow:
            cases = await uow.cases.list_pending_law_review(self.limit)

        checked: list[str] = []
        changed: list[str] = []
        skipped: list[str] = []
        for case in cases:
            try:
                outcome = await self._review(case, context)
            except DWError as exc:
                skipped.append(f"{case.title}: {exc}")
                continue
            if outcome is None:
                skipped.append(f"{case.title}: chưa có căn cứ đã kiểm chứng để đối chiếu")
                continue
            checked.append(case.title)
            if outcome:
                changed.append(outcome)
        return LawWatchReport(tuple(checked), tuple(changed), tuple(skipped))

    async def _review(self, case: PreparationCase, context: AccessContext) -> str | None:
        """Returns "" when nothing moved, a description when it did, None when
        the case has no verified position to compare against."""
        async with self.uow_factory(TenantId(context.tenant_id)) as uow:
            approach = await uow.artifacts.latest(case.id, ArtifactType.PROCUREMENT_APPROACH)
        if approach is None:
            return None
        drafted = LegalPosition.from_artifact(approach.content)
        if drafted is None or drafted.min_bid_preparation_days is None:
            return None

        current = await self.read_current(case, context)
        if current is None or current.min_bid_preparation_days is None:
            # Sources unreachable or nothing verifiable came back. Silence beats
            # "the law changed" on the strength of a failed lookup.
            return None
        if not drafted.differs_from(current):
            await self._record(case, context, drafted, current, changed=False)
            return ""

        guard = f"{case.id.value}:{current.fingerprint}"
        await self._record(case, context, drafted, current, changed=True)
        if guard not in self._announced:
            await self._alert(case, context, drafted, current)
            self._announced.add(guard)
        return (
            f"{case.title}: {drafted.min_bid_preparation_days} → "
            f"{current.min_bid_preparation_days} ngày "
            f"({current.article_ref or 'căn cứ mới'})"
        )

    async def _record(
        self,
        case: PreparationCase,
        context: AccessContext,
        drafted: LegalPosition,
        current: LegalPosition,
        *,
        changed: bool,
    ) -> None:
        """Every sweep leaves a trace, including the quiet ones.

        "We checked and it still holds" is the answer to an auditor asking what
        the package was measured against, and it only exists if unchanged
        results are written down too.
        """
        from dw_tender.application.preparation.handlers import _add_application_artifact

        async with self.uow_factory(TenantId(context.tenant_id)) as uow:
            await _add_application_artifact(
                uow=uow,
                id_generator=self.id_generator,
                case=case,
                actor=UserId(context.principal_id),
                artifact_type=ArtifactType.LAW_REVIEW,
                content={
                    "reviewed_at": self.clock.now().isoformat(),
                    "changed": changed,
                    "drafted_with": {
                        "min_bid_preparation_days": drafted.min_bid_preparation_days,
                        "article_ref": drafted.article_ref,
                    },
                    "sources_now_say": {
                        "min_bid_preparation_days": current.min_bid_preparation_days,
                        "article_ref": current.article_ref,
                        "source_quote": current.source_quote[:400],
                    },
                },
                status=ArtifactStatus.DRAFT,
            )
            await uow.commit()

    async def _alert(
        self,
        case: PreparationCase,
        context: AccessContext,
        drafted: LegalPosition,
        current: LegalPosition,
    ) -> None:
        checkpoint = _CHECKPOINT_FOR_STATE.get(case.state, "CP2")
        role = self.rules.approver_role_for(case.estimated_value_minor, checkpoint)
        async with self.uow_factory(TenantId(context.tenant_id)) as uow:
            recipient = await uow.notifications.find_recipient_for_role(role)
            if recipient is None:  # role unstaffed → the alert must still land
                recipient = await uow.notifications.find_recipient_for_role(
                    self.rules.default_approver_role
                )
            if recipient is None:
                return
            lines = [
                f"Khi soạn hồ sơ: tối thiểu {drafted.min_bid_preparation_days} ngày"
                + (f" ({drafted.article_ref})" if drafted.article_ref else ""),
                f"Nguồn hiện nay: tối thiểu {current.min_bid_preparation_days} ngày"
                + (f" ({current.article_ref})" if current.article_ref else ""),
            ]
            if current.source_quote:
                lines.append(f"«{current.source_quote[:300]}»")
            lines.append(
                "Phiếu duyệt vẫn còn hiệu lực — đây là thông tin để bạn quyết. "
                "Muốn áp mốc mới thì sửa hồ sơ, hệ thống sẽ thu hồi phiếu và chạy lại phép kiểm."
            )
            await uow.notifications.enqueue(
                IntakeNotificationJob(
                    id=self.id_generator.new_uuid(),
                    tenant_id=TenantId(context.tenant_id),
                    workspace_id=case.workspace_id,
                    case_id=PreparationCaseId(case.id.value),
                    event_type=IntakeNotificationType.LAW_CHANGE_DETECTED,
                    recipient_user_id=recipient,
                    due_at=self.clock.now(),
                    # Keyed by what the law now says: the same change reported
                    # once, however many sweeps see it.
                    idempotency_key=f"law-change:{case.id.value}:{current.fingerprint}",
                    payload={
                        "title": f"Luật đã thay đổi — {case.title}",
                        "lines": lines,
                        "case_id": str(case.id.value),
                        "article_ref": current.article_ref,
                        "before": drafted.min_bid_preparation_days,
                        "after": current.min_bid_preparation_days,
                    },
                )
            )
            await uow.commit()
