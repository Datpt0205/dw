"""LangGraph implementation of ``WorkflowRunnerPort`` (ADR-004).

Responsibilities:
- compile registered graphs with the tenant-aware checkpoint saver;
- persist run lifecycle in platform.worker_runs;
- map LangGraph interrupts to platform ApprovalRequests (pause);
- resume a durable run from its checkpoint after approval — including after a
  full process restart, since all state lives in PostgreSQL.

LangGraph never leaks outside this adapter (import-linter enforced).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC
from typing import Any

from langgraph.types import Command

from dw_agent_runtime.adapters.checkpoint import SqlAlchemyCheckpointSaver
from dw_agent_runtime.adapters.run_store import RunStatus, SqlWorkerRunStore
from dw_agent_runtime.context import access_context_from_run
from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.registry import GraphRegistry, WorkerRegistry
from dw_kernel.errors import ConflictError, InfrastructureError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.ports import IdGenerator, UtcClock
from dw_platform.application.ports import PlatformUnitOfWorkFactory
from dw_platform.domain.approval import ApprovalRequest
from dw_platform.domain.audit import AuditEvent


def _jsonable(value: Any) -> Any:
    """Best-effort conversion of graph state to JSON-storable data."""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items() if not str(k).startswith("__")}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


@dataclass
class LangGraphWorkflowRunner:
    """Implements ``WorkflowRunnerPort`` on LangGraph + PostgreSQL."""

    worker_registry: WorkerRegistry
    graph_registry: GraphRegistry
    checkpoint_saver: SqlAlchemyCheckpointSaver
    run_store: SqlWorkerRunStore
    uow_factory: PlatformUnitOfWorkFactory
    clock: UtcClock
    id_generator: IdGenerator
    _compiled: dict[tuple[str, str], Any] = field(default_factory=dict)

    def _graph(self, worker_id: str, graph_version: str) -> Any:
        key = (worker_id, graph_version)
        if key not in self._compiled:
            factory = self.graph_registry.resolve(worker_id, graph_version)
            self._compiled[key] = factory().compile(checkpointer=self.checkpoint_saver)
        return self._compiled[key]

    def _config(self, run_context: RunContext, run_id: uuid.UUID) -> dict[str, Any]:
        return {
            "configurable": {
                "thread_id": str(run_id),
                "tenant_id": str(run_context.tenant_id),
                "workspace_id": str(run_context.workspace_id),
                "run_context": run_context,
            }
        }

    # ---------------------------------------------------------------- start --
    async def start(
        self,
        *,
        run_context: RunContext,
        input_payload: dict[str, Any],
    ) -> uuid.UUID:
        worker = self.worker_registry.resolve(run_context.worker_id, run_context.worker_version)
        graph = self._graph(worker.definition.worker_id, worker.definition.graph_version)

        await self.run_store.create(
            run_context,
            graph_version=worker.definition.graph_version,
            input_payload=input_payload,
        )
        await self._audit(run_context, "run.started", str(run_context.run_id))

        state = await graph.ainvoke(input_payload, self._config(run_context, run_context.run_id))
        await self._handle_outcome(run_context, run_context.run_id, state)
        return run_context.run_id

    # --------------------------------------------------------------- resume --
    async def resume(
        self,
        *,
        run_context: RunContext,
        run_id: uuid.UUID,
        resume_payload: dict[str, Any],
    ) -> None:
        record = await self.run_store.get(run_context, run_id)
        if record.status is not RunStatus.WAITING_APPROVAL:
            raise ConflictError(
                "run is not waiting for approval",
                details={"run_id": str(run_id), "status": record.status.value},
            )
        graph = self._graph(record.worker_id, record.graph_version)

        await self._audit(run_context, "run.resumed", str(run_id))
        state = await graph.ainvoke(
            Command(resume=resume_payload), self._config(run_context, run_id)
        )
        await self._handle_outcome(run_context, run_id, state)

    # -------------------------------------------------------------- outcome --
    async def _handle_outcome(
        self, run_context: RunContext, run_id: uuid.UUID, state: dict[str, Any]
    ) -> None:
        interrupts = state.get("__interrupt__") if isinstance(state, dict) else None
        if interrupts:
            payload = interrupts[0].value if hasattr(interrupts[0], "value") else interrupts[0]
            if not isinstance(payload, dict):
                payload = {"value": _jsonable(payload)}
            approval_id = await self._create_approval(run_context, run_id, payload)
            await self.run_store.set_status(
                run_context,
                run_id,
                RunStatus.WAITING_APPROVAL,
                approval_request_id=approval_id,
            )
            await self._audit(
                run_context,
                "run.waiting_approval",
                str(run_id),
                details={"approval_request_id": str(approval_id)},
            )
            return

        await self.run_store.set_status(
            run_context, run_id, RunStatus.COMPLETED, result=_jsonable(state)
        )
        await self._audit(run_context, "run.completed", str(run_id))

    async def _create_approval(
        self, run_context: RunContext, run_id: uuid.UUID, payload: dict[str, Any]
    ) -> uuid.UUID:
        approval = ApprovalRequest(
            id=self.id_generator.new_uuid(),
            tenant_id=TenantId(run_context.tenant_id),
            workspace_id=WorkspaceId(run_context.workspace_id),
            approval_type=str(payload.get("approval_type", "workflow.review")),
            requested_by=UserId(run_context.actor_id),
            reason=str(payload.get("reason", "workflow requested human review")),
            payload=_jsonable(payload),
            run_id=run_id,
        )
        context = access_context_from_run(run_context)
        async with self.uow_factory(context) as uow:
            await uow.approvals.add(approval)
            await uow.commit()
        return approval.id

    async def _audit(
        self,
        run_context: RunContext,
        action: str,
        resource_id: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        context = access_context_from_run(run_context)
        event = AuditEvent(
            id=self.id_generator.new_uuid(),
            tenant_id=TenantId(run_context.tenant_id),
            workspace_id=WorkspaceId(run_context.workspace_id),
            actor_id=UserId(run_context.actor_id),
            action=action,
            resource_type="worker_run",
            resource_id=resource_id,
            run_id=run_context.run_id,
            trace_id=run_context.trace_id,
            details=details or {},
            occurred_at=self.clock.now().astimezone(UTC),
        )
        try:
            async with self.uow_factory(context) as uow:
                await uow.audit.append(event)
                await uow.commit()
        except Exception as exc:
            raise InfrastructureError(
                "failed to write audit event", details={"action": action}
            ) from exc
