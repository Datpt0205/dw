"""Persistence for worker runs (platform.worker_runs) under RLS."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_agent_runtime.adapters.runtime_tables import worker_runs
from dw_agent_runtime.contracts import RunContext
from dw_kernel.errors import NotFoundError


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


_SET_TENANT = text("SELECT set_config('app.tenant_id', :tenant_id, true)")


@dataclass(frozen=True)
class RunRecord:
    id: uuid.UUID
    status: RunStatus
    worker_id: str
    worker_version: str
    graph_version: str
    input: dict[str, Any]
    result: dict[str, Any] | None
    error: dict[str, Any] | None
    approval_request_id: uuid.UUID | None
    release_manifest_ref: str | None


@dataclass(frozen=True)
class SqlWorkerRunStore:
    session_factory: async_sessionmaker[AsyncSession]

    async def _execute(self, run_context: RunContext, statement: sa.Executable) -> Any:
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"tenant_id": str(run_context.tenant_id)})
            return await session.execute(statement)

    async def create(
        self,
        run_context: RunContext,
        *,
        graph_version: str,
        input_payload: dict[str, Any],
        release_manifest_ref: str | None = None,
    ) -> None:
        await self._execute(
            run_context,
            sa.insert(worker_runs).values(
                id=run_context.run_id,
                tenant_id=run_context.tenant_id,
                workspace_id=run_context.workspace_id,
                worker_id=run_context.worker_id,
                worker_version=run_context.worker_version,
                graph_version=graph_version,
                status=RunStatus.RUNNING.value,
                input=input_payload,
                requested_by=run_context.actor_id,
                trace_id=run_context.trace_id,
                release_manifest_ref=release_manifest_ref,
                created_at=sa.func.now(),
                updated_at=sa.func.now(),
            ),
        )

    async def set_status(
        self,
        run_context: RunContext,
        run_id: uuid.UUID,
        status: RunStatus,
        *,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        approval_request_id: uuid.UUID | None = None,
    ) -> None:
        values: dict[str, Any] = {"status": status.value, "updated_at": sa.func.now()}
        if result is not None:
            values["result"] = result
        if error is not None:
            values["error"] = error
        if approval_request_id is not None:
            values["approval_request_id"] = approval_request_id
        await self._execute(
            run_context,
            sa.update(worker_runs).where(worker_runs.c.id == run_id).values(**values),
        )

    async def get(self, run_context: RunContext, run_id: uuid.UUID) -> RunRecord:
        result = await self._execute(
            run_context, sa.select(worker_runs).where(worker_runs.c.id == run_id)
        )
        row = result.first()
        if row is None:
            raise NotFoundError("run not found", details={"run_id": str(run_id)})
        return RunRecord(
            id=row.id,
            status=RunStatus(row.status),
            worker_id=row.worker_id,
            worker_version=row.worker_version,
            graph_version=row.graph_version,
            input=dict(row.input),
            result=dict(row.result) if row.result is not None else None,
            error=dict(row.error) if row.error is not None else None,
            approval_request_id=row.approval_request_id,
            release_manifest_ref=row.release_manifest_ref,
        )
