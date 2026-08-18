"""Change what was asked for, while changing it is still cheap.

Until CP2 is signed the package is internal: nobody outside has seen it, so a
correction costs a re-check and nothing else. The system used to offer no way
to make one. A requester who mistyped a budget, or an approver who wanted a
longer warranty, had exactly two options — abandon the case, or approve
something wrong and fix it afterwards as an addendum.

Two things make this safe rather than merely possible. A pending checkpoint is
WITHDRAWN, not left standing: an approver must never be looking at a card for
a version that no longer exists, and must be told the ground moved under them.
And the run starts again, so every gate is re-evaluated against the new
numbers instead of inheriting a verdict earned by the old ones.

After CP2 the answer is no, and that is not a limitation — the package has
gone out to suppliers, and a change only some of them hear about is an unfair
one. That is what an addendum is for.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from dw_kernel.errors import ConflictError, DomainError, NotFoundError
from dw_kernel.ids import TenantId, UserId
from dw_kernel.ports import IdGenerator, UtcClock
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.ports import PlatformUnitOfWorkFactory
from dw_tender.application.preparation.handlers import (
    RunPreparationHandler,
    _add_application_artifact,
)
from dw_tender.application.preparation.ports import PreparationUnitOfWorkFactory
from dw_tender.domain.preparation.entities import (
    ArtifactStatus,
    ArtifactType,
    PreparationCase,
)
from dw_tender.domain.preparation.notifications import (
    IntakeNotificationJob,
    IntakeNotificationType,
)
from dw_tender.domain.value_objects.ids import PreparationCaseId


@dataclass(frozen=True, slots=True)
class AmendCaseCommand:
    """Only the fields a person actually revises. Absent means unchanged."""

    estimated_value_minor: int | None = None
    deadline: str | None = None
    supplier_names: tuple[str, ...] | None = None
    note: str = ""


@dataclass(frozen=True, slots=True)
class AmendResult:
    case_id: uuid.UUID
    changes: tuple[str, ...]
    withdrew_checkpoint: str
    rerun_id: uuid.UUID | None


def _describe(field: str, before: object, after: object) -> str:
    return f"{field}: {before} → {after}"


@dataclass
class AmendPreparationCaseHandler:
    uow_factory: PreparationUnitOfWorkFactory
    platform_uow_factory: PlatformUnitOfWorkFactory
    authorization: ScopeAuthorizationService
    clock: UtcClock
    id_generator: IdGenerator
    run_case: RunPreparationHandler | None = None

    async def handle(
        self, case_id: uuid.UUID, command: AmendCaseCommand, context: AccessContext
    ) -> AmendResult:
        await self.authorization.require(
            context=context,
            action="tender.write",
            resource_type="preparation_case",
            resource_id=str(case_id),
        )
        async with self.uow_factory(TenantId(context.tenant_id)) as uow:
            case = await uow.cases.get(PreparationCaseId(case_id))
            if case is None:
                raise NotFoundError("preparation case not found", details={"case_id": str(case_id)})
            if not case.state.accepts_amendment:
                raise ConflictError(
                    "the package is already official — a change now needs an addendum",
                    details={"case_id": str(case_id), "state": case.state.value},
                )
            changes = self._apply(case, command)
            if command.supplier_names is not None:
                # Suppliers live on an artifact, not on the case, so changing
                # them means writing a new version of that artifact. Reporting
                # the change without writing it would be the exact failure the
                # receipt layer exists to prevent.
                previous = await uow.artifacts.latest(case.id, ArtifactType.SUPPLIER_INPUT)
                stored = previous.content.get("suppliers") if previous else None
                before = [
                    str(item.get("name", ""))
                    for item in (stored if isinstance(stored, list) else [])
                    if isinstance(item, dict)
                ]
                after = [name.strip() for name in command.supplier_names if name.strip()]
                if after and after != before:
                    await _add_application_artifact(
                        uow=uow,
                        id_generator=self.id_generator,
                        case=case,
                        actor=UserId(context.principal_id),
                        artifact_type=ArtifactType.SUPPLIER_INPUT,
                        content={
                            "source": "chat_amendment",
                            "suppliers": [{"name": n} for n in after],
                        },
                        status=ArtifactStatus.DRAFT,
                    )
                    changes = (
                        *changes,
                        _describe(
                            "nhà cung cấp mời", ", ".join(before) or "(chưa có)", ", ".join(after)
                        ),
                    )
            if not changes:
                raise DomainError("nothing to change")

            await _add_application_artifact(
                uow=uow,
                id_generator=self.id_generator,
                case=case,
                actor=UserId(context.principal_id),
                artifact_type=ArtifactType.DEMAND_SNAPSHOT,
                content={
                    "amended_at": self.clock.now().isoformat(),
                    "amended_by": str(context.principal_id),
                    "changes": list(changes),
                    "note": command.note[:400],
                    "estimated_value_minor": case.estimated_value_minor,
                    "deadline": case.deadline,
                },
                status=ArtifactStatus.DRAFT,
            )
            # Everything after intake was derived from the old figures, so the
            # case goes back to the start of the derivation. Without this the
            # re-run below is refused and the case is left stranded: its
            # checkpoint withdrawn, nothing running, nobody able to act.
            case.reopen_for_amendment()
            await uow.cases.save(case)
            await uow.commit()

        withdrew = await self._withdraw_pending_checkpoint(case_id, changes, context)
        rerun_id = None
        if self.run_case is not None:
            # Every gate is re-evaluated against the new numbers. A verdict
            # earned by the old ones does not carry over.
            rerun_id = await self.run_case.handle(case_id, context, channel="amend")
        return AmendResult(
            case_id=case_id,
            changes=changes,
            withdrew_checkpoint=withdrew,
            rerun_id=rerun_id,
        )

    def _apply(self, case: PreparationCase, command: AmendCaseCommand) -> tuple[str, ...]:
        changed: list[str] = []
        if (
            command.estimated_value_minor is not None
            and command.estimated_value_minor != case.estimated_value_minor
        ):
            changed.append(
                _describe("giá trị gói", case.estimated_value_minor, command.estimated_value_minor)
            )
            case.estimated_value_minor = command.estimated_value_minor
        if command.deadline is not None and command.deadline != case.deadline:
            changed.append(_describe("thời hạn", case.deadline, command.deadline))
            case.deadline = command.deadline
        # No version bump here: the repository allows exactly one increment
        # between load and save, and every amendment ends in
        # ``reopen_for_amendment`` which supplies it.
        return tuple(changed)

    async def _withdraw_pending_checkpoint(
        self, case_id: uuid.UUID, changes: tuple[str, ...], context: AccessContext
    ) -> str:
        """Cancel any checkpoint still waiting, and say so to whoever held it.

        Leaving it standing would let a package be approved on the strength of
        a card describing figures that are no longer in the case.
        """
        async with self.platform_uow_factory(context) as uow:
            withdrawn = ""
            for request in await uow.approvals.list_pending():
                if not request.approval_type.startswith("preparation."):
                    continue
                if str(request.payload.get("case_id", "")) != str(case_id):
                    continue
                request.cancel()
                await uow.approvals.save(request)
                # "preparation.cp2" is a wire name; the person waiting on it
                # knows it as CP2.
                withdrawn = str(request.payload.get("checkpoint", "")) or (
                    request.approval_type.rpartition(".")[2].upper()
                )
            if withdrawn:
                await uow.commit()
        if not withdrawn:
            return ""

        async with self.uow_factory(TenantId(context.tenant_id)) as uow:
            case = await uow.cases.get(PreparationCaseId(case_id))
            assert case is not None
            await uow.notifications.enqueue(
                IntakeNotificationJob(
                    id=self.id_generator.new_uuid(),
                    tenant_id=case.tenant_id,
                    workspace_id=case.workspace_id,
                    case_id=case.id,
                    event_type=IntakeNotificationType.RUN_PROGRESS,
                    recipient_user_id=case.created_by,
                    due_at=self.clock.now(),
                    idempotency_key=f"dw01:{case_id}:amended:v{case.version}",
                    payload={
                        "title": case.title,
                        "heading": f"⚠️ Hồ sơ vừa được sửa — thu hồi phiếu {withdrawn}",
                        "lines": [
                            *changes,
                            f"Phiếu duyệt {withdrawn} cho bản cũ đã được thu hồi.",
                            "Hồ sơ đang chạy lại các bước kiểm; sẽ trình duyệt lại khi xong.",
                        ],
                    },
                )
            )
            await uow.commit()
        return withdrawn
