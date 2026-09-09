"""Submitting the justification a full quota asks for.

Only submission lives here. Deciding one, listing the pending ones and
escalating a stale one are already implemented for rework support and are
kind-agnostic, so this reuses them rather than growing a second copy of a
lifecycle that would then drift.

Submission is where the two mechanisms genuinely differ: a different counter, a
different rule pack, and no case. Someone at their quota is being stopped from
opening one — that is the whole point — so unlike a rework explanation there is
nothing yet for this to be attached to.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC

from dw_kernel.errors import DomainError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.ports import IdGenerator, UtcClock
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_tender.application.preparation.intake_quota_guard import IntakeQuotaGuard
from dw_tender.application.preparation.ports import PreparationUnitOfWorkFactory
from dw_tender.domain.preparation.notifications import (
    IntakeNotificationJob,
    IntakeNotificationType,
)
from dw_tender.domain.preparation.rework import ExplanationKind, ExplanationRecord
from dw_tender.domain.value_objects.ids import PreparationCaseId


@dataclass(frozen=True)
class SubmitQuotaJustificationCommand:
    reason_text: str


@dataclass
class SubmitQuotaJustificationHandler:
    uow_factory: PreparationUnitOfWorkFactory
    authorization: ScopeAuthorizationService
    guard: IntakeQuotaGuard
    clock: UtcClock
    id_generator: IdGenerator

    async def handle(
        self, command: SubmitQuotaJustificationCommand, context: AccessContext
    ) -> uuid.UUID:
        await self.authorization.require(
            context=context, action="tender.write", resource_type="preparation_case"
        )
        rules = self.guard.rules
        reason = command.reason_text.strip()
        if len(reason) < rules.explanation_min_chars:
            raise DomainError(
                "phần giải trình còn quá ngắn",
                details={"min_chars": rules.explanation_min_chars, "got": len(reason)},
            )

        # Assessed BEFORE writing, and what it saw is stored on the record.
        # Read back a month later the period has rolled over, and a live
        # recount would make this justification look like an answer to a
        # different set of facts than the one its author was writing about.
        assessment = await self.guard.assess(context)
        if not assessment.blocked:
            raise DomainError("chưa chạm ngưỡng nên chưa cần giải trình")

        now = self.clock.now().astimezone(UTC)
        creator = UserId(context.principal_id)
        record = ExplanationRecord(
            id=self.id_generator.new_uuid(),
            tenant_id=TenantId(context.tenant_id),
            workspace_id=WorkspaceId(context.workspace_id),
            case_id=None,
            creator_user_id=creator,
            context_text=reason,
            difficulty_text="",
            support_request_text="",
            policy_version=assessment.policy_version,
            submitted_at=now,
            block_count=assessment.used,
            kind=ExplanationKind.INTAKE_QUOTA,
        )

        async with self.uow_factory(TenantId(context.tenant_id)) as uow:
            await uow.explanations.add(record)
            await self._notify_approver(uow, record, assessment, context, now)
            await uow.commit()
        return record.id

    async def _notify_approver(
        self,
        uow: object,
        record: ExplanationRecord,
        assessment: object,
        context: AccessContext,
        now: object,
    ) -> None:
        """Push the card to whoever holds the approving role.

        The notification pipeline requires a case on every job, and this one has
        none — so it rides on the requester's most recent case, which is the
        convention the rework cards already use: the case id records where a
        person-scoped card was raised, not what it is about. It also gives the
        approver somewhere useful to land, since that case is an example of what
        this person has been filing.

        No recent case at all means no card. That is a corner nobody reaches —
        being over quota means having opened cases — and inventing a delivery
        path for it would be code with no caller.
        """
        rules = self.guard.rules
        creator = record.creator_user_id
        recipient = await uow.notifications.find_recipient_for_role(  # type: ignore[attr-defined]
            rules.approver_role, exclude=creator
        )
        if recipient is None:
            return
        recent = await uow.cases.list_opened_by(  # type: ignore[attr-defined]
            creator, since=record.submitted_at.replace(year=record.submitted_at.year - 1)
        )
        if not recent:
            return
        anchor = recent[-1].case_id

        used = getattr(assessment, "used", 0)
        threshold = getattr(assessment, "threshold", 0)
        period = getattr(assessment, "period_label", "")
        await uow.notifications.enqueue(  # type: ignore[attr-defined]
            IntakeNotificationJob(
                id=self.id_generator.new_uuid(),
                tenant_id=TenantId(context.tenant_id),
                workspace_id=WorkspaceId(context.workspace_id),
                case_id=PreparationCaseId(anchor),
                event_type=IntakeNotificationType.QUOTA_JUSTIFICATION_SUBMITTED,
                recipient_user_id=recipient,
                due_at=now,  # type: ignore[arg-type]
                idempotency_key=f"dw01:quota:justification:{record.id}",
                payload={
                    "title": "Đề nghị mở thêm yêu cầu mua sắm",
                    "heading": "📝 Xin mở thêm đợt mua sắm — cần bạn duyệt",
                    "explanation_id": str(record.id),
                    "lines": [
                        f"Đã dùng {used}/{threshold} suất của kỳ {period}.",
                        f"Lý do: {record.context_text}",
                        "Duyệt thì người này mở được đợt tiếp theo; từ chối thì không.",
                    ],
                },
            )
        )
