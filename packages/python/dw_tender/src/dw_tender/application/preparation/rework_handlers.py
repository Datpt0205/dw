"""Reading the tally, writing an explanation, deciding one, undoing a mis-click.

The four operations that sit around the pure core. Each one is thin: the
counting lives in ``rework.py``, the invariants live on the aggregate in
``domain/preparation/rework.py``, and what remains here is authorisation,
transaction boundaries, and routing the notification to a person who can help.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, timedelta

from dw_kernel.errors import ConflictError, DomainError, NotFoundError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.ports import IdGenerator, UtcClock
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_tender.application.preparation.ports import PreparationUnitOfWorkFactory
from dw_tender.application.preparation.rework import ReworkAssessment, SupportLevel
from dw_tender.application.preparation.rework_guard import ReworkGuard
from dw_tender.application.preparation.rework_wording import supporter_lines
from dw_tender.domain.preparation.notifications import (
    IntakeNotificationJob,
    IntakeNotificationType,
)
from dw_tender.domain.preparation.rework import ExplanationRecord
from dw_tender.domain.value_objects.ids import PreparationCaseId


@dataclass
class AssessReworkSupportHandler:
    """What the support ladder says about the caller, for their own page."""

    guard: ReworkGuard

    async def handle(self, context: AccessContext) -> ReworkAssessment:
        # No authorization check: a person always sees their own figures,
        # whatever role they hold. Showing someone else's is a different
        # operation with a different gate.
        return await self.guard.assess(context)


@dataclass(frozen=True)
class SubmitExplanationCommand:
    context_text: str
    difficulty_text: str = ""
    support_request_text: str = ""
    case_id: uuid.UUID | None = None


@dataclass
class SubmitExplanationHandler:
    uow_factory: PreparationUnitOfWorkFactory
    authorization: ScopeAuthorizationService
    guard: ReworkGuard
    clock: UtcClock
    id_generator: IdGenerator

    async def handle(self, command: SubmitExplanationCommand, context: AccessContext) -> uuid.UUID:
        await self.authorization.require(
            context=context, action="tender.write", resource_type="preparation_case"
        )
        rules = self.guard.rules
        text = command.context_text.strip()
        if len(text) < rules.explanation_min_chars:
            raise DomainError(
                "phần mô tả bối cảnh còn quá ngắn",
                details={"min_chars": rules.explanation_min_chars, "got": len(text)},
            )

        # Assess BEFORE writing, and store what it saw. Reopened three weeks
        # later the window has moved on, and a live recount would make this
        # explanation look like an answer to a different set of facts than the
        # one its author was actually writing about.
        assessment = await self.guard.assess(context)
        now = self.clock.now().astimezone(UTC)
        creator = UserId(context.principal_id)

        record = ExplanationRecord(
            id=self.id_generator.new_uuid(),
            tenant_id=TenantId(context.tenant_id),
            workspace_id=WorkspaceId(context.workspace_id),
            case_id=PreparationCaseId(command.case_id) if command.case_id else None,
            creator_user_id=creator,
            context_text=text,
            difficulty_text=command.difficulty_text.strip(),
            support_request_text=command.support_request_text.strip(),
            policy_version=assessment.policy_version,
            submitted_at=now,
            counted_event_ids=assessment.counted_event_ids,
            nudge_count=assessment.nudge_count,
            block_count=assessment.block_count,
            top_reason_code=assessment.top_reason_code or "",
        )

        async with self.uow_factory(TenantId(context.tenant_id)) as uow:
            await uow.explanations.add(record)
            # Only summon a helper when someone is actually held up. A nudge
            # is between the requester and their own page; pulling the head of
            # procurement into every one of those would empty the signal of
            # meaning within a fortnight.
            if assessment.level is SupportLevel.BLOCK and command.case_id is not None:
                recipient = await uow.notifications.find_recipient_for_role(
                    rules.supporter_role, exclude=creator
                )
                if recipient is not None:
                    await uow.notifications.enqueue(
                        IntakeNotificationJob(
                            id=self.id_generator.new_uuid(),
                            tenant_id=TenantId(context.tenant_id),
                            workspace_id=WorkspaceId(context.workspace_id),
                            case_id=PreparationCaseId(command.case_id),
                            event_type=IntakeNotificationType.REWORK_SUPPORT_REQUIRED,
                            recipient_user_id=recipient,
                            due_at=now,
                            idempotency_key=f"dw01:rework:explanation:{record.id}",
                            payload={
                                "explanation_id": str(record.id),
                                "lines": supporter_lines(
                                    assessment, creator_label="Người tạo hồ sơ"
                                ),
                                "block_count": assessment.block_count,
                            },
                        )
                    )
            await uow.commit()
        return record.id


@dataclass
class ListPendingExplanationsHandler:
    """The queue of people waiting to be unblocked.

    Gated twice, like the decision itself: the caller must be allowed to
    decide things at all, AND hold the role the rule pack routes these to.
    This is the one place where one person's figures are shown to another, so
    the second check is what keeps it from becoming a roster of who has been
    struggling.
    """

    uow_factory: PreparationUnitOfWorkFactory
    authorization: ScopeAuthorizationService
    guard: ReworkGuard

    async def handle(self, context: AccessContext) -> list[ExplanationRecord]:
        await self.authorization.require(
            context=context,
            action="approvals.decide",
            resource_type="preparation_explanation",
        )
        required_role = self.guard.rules.supporter_role
        if required_role and required_role not in context.roles:
            raise ConflictError(
                "danh sách này dành cho vai trò khác xem",
                details={"required_role": required_role},
            )
        async with self.uow_factory(TenantId(context.tenant_id)) as uow:
            return await uow.explanations.list_pending()


@dataclass
class DecideExplanationHandler:
    uow_factory: PreparationUnitOfWorkFactory
    authorization: ScopeAuthorizationService
    guard: ReworkGuard
    clock: UtcClock

    async def handle(
        self,
        explanation_id: uuid.UUID,
        *,
        approve: bool,
        comment: str,
        context: AccessContext,
    ) -> None:
        # Two separate checks, on purpose. Holding approvals.decide says you
        # may decide things; holding the configured role says you may decide
        # THIS. Collapsing them would let any approver lift any block.
        await self.authorization.require(
            context=context,
            action="approvals.decide",
            resource_type="preparation_explanation",
            resource_id=str(explanation_id),
        )
        required_role = self.guard.rules.supporter_role
        if required_role and required_role not in context.roles:
            raise ConflictError(
                "phần mô tả này dành cho vai trò khác xem",
                details={"required_role": required_role},
            )

        async with self.uow_factory(TenantId(context.tenant_id)) as uow:
            record = await uow.explanations.get(explanation_id)
            if record is None:
                raise NotFoundError("explanation not found")
            # Decided once, never by its author, never without a note back —
            # all three enforced on the aggregate.
            record.decide(
                approve=approve,
                decided_by=UserId(context.principal_id),
                decided_at=self.clock.now().astimezone(UTC),
                comment=comment,
            )
            await uow.explanations.save(record)
            await uow.commit()


@dataclass
class VoidReworkEventHandler:
    """Undo a mis-click.

    The row stays readable — the correction is itself a fact worth keeping —
    but it leaves the tally. Without this a slip of the mouse would sit in
    someone's count for a month, and the first thing that count does is decide
    whether they may work.
    """

    uow_factory: PreparationUnitOfWorkFactory
    authorization: ScopeAuthorizationService
    clock: UtcClock

    async def handle(self, event_id: uuid.UUID, *, reason: str, context: AccessContext) -> None:
        await self.authorization.require(
            context=context,
            action="approvals.decide",
            resource_type="preparation_rework_event",
            resource_id=str(event_id),
        )
        note = reason.strip()
        if not note:
            raise DomainError("undoing a recorded return requires a reason")
        async with self.uow_factory(TenantId(context.tenant_id)) as uow:
            event = await uow.rework_events.get(event_id)
            if event is None:
                raise NotFoundError("rework event not found")
            if event.voided:
                raise ConflictError("this record has already been corrected")
            await uow.rework_events.void(
                event_id,
                voided_by=UserId(context.principal_id),
                reason=note,
                at=self.clock.now().astimezone(UTC),
            )
            await uow.commit()


@dataclass
class EscalateStaleExplanationsHandler:
    """Nobody picked it up in time.

    The worst state this mechanism can produce is a person blocked and waiting
    on a queue nobody is reading, so this exists to make that state loud.
    """

    uow_factory: PreparationUnitOfWorkFactory
    guard: ReworkGuard
    clock: UtcClock
    id_generator: IdGenerator

    async def handle(self, tenant_id: uuid.UUID) -> int:
        rules = self.guard.rules
        if not rules.is_enabled() or rules.escalate_after_hours <= 0:
            return 0
        now = self.clock.now().astimezone(UTC)
        cutoff = now - timedelta(hours=rules.escalate_after_hours)
        escalated = 0
        async with self.uow_factory(TenantId(tenant_id)) as uow:
            for record in await uow.explanations.list_pending_overdue(before=cutoff):
                if record.case_id is None:
                    continue
                recipient = await uow.notifications.find_recipient_for_role(
                    "platform_admin", exclude=record.creator_user_id
                )
                if recipient is None:
                    continue
                await uow.notifications.enqueue(
                    IntakeNotificationJob(
                        id=self.id_generator.new_uuid(),
                        tenant_id=record.tenant_id,
                        workspace_id=record.workspace_id,
                        case_id=record.case_id,
                        event_type=IntakeNotificationType.REWORK_EXPLANATION_ESCALATED,
                        recipient_user_id=recipient,
                        due_at=now,
                        # One escalation per explanation, whatever the scanner
                        # cadence: the unique index on this key turns repeat
                        # sweeps into no-ops.
                        idempotency_key=f"dw01:rework:escalated:{record.id}",
                        payload={"explanation_id": str(record.id)},
                    )
                )
                escalated += 1
            await uow.commit()
        return escalated
