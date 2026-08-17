"""Approve/reject a pending approval and resume its paused run.

Bridges platform approvals and the workflow runner: the human decision is
persisted first (aggregate invariant: decided exactly once), then the durable
run resumes with the decision payload.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC
from typing import Any

from dw_agent_runtime.adapters.run_store import SqlWorkerRunStore
from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.ports import WorkflowRunnerPort
from dw_kernel.errors import ConflictError, NotFoundError
from dw_kernel.ids import UserId
from dw_kernel.ports import IdGenerator, UtcClock
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.ports import PlatformUnitOfWorkFactory
from dw_platform.domain.approval import ApprovalRequest, DecisionOutcome


@dataclass
class ApproveAndResumeService:
    uow_factory: PlatformUnitOfWorkFactory
    runner: WorkflowRunnerPort
    run_store: SqlWorkerRunStore
    clock: UtcClock
    id_generator: IdGenerator

    async def decide(
        self,
        *,
        approval_id: uuid.UUID,
        approve: bool,
        comment: str,
        context: AccessContext,
        authorization: ScopeAuthorizationService,
        # Where the human actually decided. Required on purpose: it used to be
        # hardcoded "web", so every checkpoint approved from chat was filed as
        # a web decision — and "who decided, from where" is precisely what an
        # audit trail is for. Only the boundary knows this; make it say so.
        channel: str,
        approved_action_ids: list[str] | None = None,
    ) -> ApprovalRequest:
        await authorization.require(
            context=context,
            action="approvals.decide",
            resource_type="approval_request",
            resource_id=str(approval_id),
        )

        async with self.uow_factory(context) as uow:
            request = await uow.approvals.get(approval_id)
            if request is None:
                raise NotFoundError(
                    "approval request not found", details={"approval_id": str(approval_id)}
                )
            if (
                request.approval_type.startswith("preparation.")
                and request.requested_by.value == context.principal_id
            ):
                raise ConflictError(
                    "separation of duties: requester cannot approve their own DW01 checkpoint",
                    details={
                        "approval_id": str(approval_id),
                        "approval_type": request.approval_type,
                    },
                )
            # Authority, not just routing: a checkpoint may name the role that
            # is allowed to decide it (stamped from the versioned approval
            # matrix when the request was raised). Holding approvals.decide is
            # not enough — a specialist must not sign off a package that the
            # rule pack sends to the head of procurement.
            required_role = str(request.payload.get("required_role", "") or "")
            if required_role and required_role not in context.roles:
                raise ConflictError(
                    "this checkpoint is reserved for another role",
                    details={
                        "approval_id": str(approval_id),
                        "approval_type": request.approval_type,
                        "required_role": required_role,
                    },
                )
            if request.approval_type.startswith("preparation.") and not comment.strip():
                raise ConflictError(
                    "DW01 checkpoint decisions require a review comment",
                    details={"approval_type": request.approval_type},
                )
            decision = request.decide(
                decision_id=self.id_generator.new_uuid(),
                decided_by=UserId(context.principal_id),
                outcome=DecisionOutcome.APPROVED if approve else DecisionOutcome.REJECTED,
                decided_at=self.clock.now().astimezone(UTC),
                comment=comment,
            )
            await uow.approvals.save(request)
            await uow.approvals.add_decision(decision)
            await uow.commit()

        if request.run_id is not None:
            record = await self.run_store.get(
                self._run_context_for(context, request.run_id, channel), request.run_id
            )
            resume_payload: dict[str, Any] = {"approved": approve, "comment": comment}
            if approved_action_ids is not None:
                resume_payload["approved_action_ids"] = approved_action_ids
            await self.runner.resume(
                run_context=RunContext(
                    run_id=request.run_id,
                    tenant_id=context.tenant_id,
                    workspace_id=context.workspace_id,
                    # Continue on behalf of the original run requester. The
                    # approver identity is already persisted immutably on the
                    # ApprovalDecision; using it here would incorrectly make
                    # that approver the requester of the next checkpoint.
                    actor_id=record.requested_by,
                    worker_id=record.worker_id,
                    worker_version=record.worker_version,
                    channel=channel,
                    plan_id=context.plan_id,
                    roles=context.roles,
                    scopes=context.scopes,
                    trace_id=f"resume-{request.run_id.hex[:12]}",
                ),
                run_id=request.run_id,
                resume_payload=resume_payload,
            )
        return request

    def _run_context_for(
        self, context: AccessContext, run_id: uuid.UUID, channel: str
    ) -> RunContext:
        """A context solely to read the run row back.

        Which worker owns this run is stored ON the row we are about to read,
        so there is nothing truthful to put here yet — hence the placeholders.
        ``RunStore`` uses only ``tenant_id`` from this (RLS scoping) and never
        persists any of it, so nothing downstream is stamped "unknown"; the
        resume above re-reads the real worker id and version off the record.
        Narrowing ``RunStore.get`` to take a tenant would delete this shim.
        """
        return RunContext(
            run_id=run_id,
            tenant_id=context.tenant_id,
            workspace_id=context.workspace_id,
            actor_id=context.principal_id,
            worker_id="unknown",
            worker_version="0.0.0",
            channel=channel,
            plan_id=context.plan_id,
            roles=context.roles,
            scopes=context.scopes,
            trace_id=f"lookup-{run_id.hex[:12]}",
        )
