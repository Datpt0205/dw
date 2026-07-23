"""Append-only persistence of tool executions with idempotency lookup."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_agent_runtime.adapters.runtime_tables import tool_executions
from dw_agent_runtime.contracts import RunContext

_SET_TENANT = text("SELECT set_config('app.tenant_id', :tenant_id, true)")


@dataclass(frozen=True)
class StoredExecution:
    id: uuid.UUID
    status: str
    input_hash: str
    output_hash: str | None
    output: dict[str, Any] | None


@dataclass(frozen=True)
class SqlToolExecutionStore:
    session_factory: async_sessionmaker[AsyncSession]

    async def find_succeeded(
        self, run_context: RunContext, tool_name: str, idempotency_key: str
    ) -> StoredExecution | None:
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"tenant_id": str(run_context.tenant_id)})
            row = (
                await session.execute(
                    sa.select(tool_executions).where(
                        tool_executions.c.tool_name == tool_name,
                        tool_executions.c.idempotency_key == idempotency_key,
                        tool_executions.c.status == "succeeded",
                    )
                )
            ).first()
        if row is None:
            return None
        return StoredExecution(
            id=row.id,
            status=row.status,
            input_hash=row.input_hash,
            output_hash=row.output_hash,
            output=dict(row.output) if row.output is not None else None,
        )

    async def record(
        self,
        run_context: RunContext,
        *,
        execution_id: uuid.UUID,
        tool_name: str,
        tool_version: str,
        status: str,
        input_hash: str,
        output_hash: str | None,
        output: dict[str, Any] | None,
        idempotency_key: str | None,
        error: str | None,
        attempts: int,
        started_at: datetime,
        finished_at: datetime,
    ) -> None:
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"tenant_id": str(run_context.tenant_id)})
            await session.execute(
                sa.insert(tool_executions).values(
                    id=execution_id,
                    tenant_id=run_context.tenant_id,
                    workspace_id=run_context.workspace_id,
                    run_id=run_context.run_id,
                    tool_name=tool_name,
                    tool_version=tool_version,
                    status=status,
                    idempotency_key=idempotency_key,
                    input_hash=input_hash,
                    output_hash=output_hash,
                    output=output,
                    error=error,
                    attempts=attempts,
                    started_at=started_at,
                    finished_at=finished_at,
                )
            )
