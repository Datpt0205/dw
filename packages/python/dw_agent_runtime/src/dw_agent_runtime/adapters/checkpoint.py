"""Tenant-aware LangGraph checkpoint saver backed by platform.run_checkpoints.

Checkpoints are the durable state of a run (blueprint §14.1 "working state").
Rows carry tenant_id and sit behind RLS: the saver sets the transaction-local
tenant context from the runner-provided config before every statement.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from typing import Any, cast

import sqlalchemy as sa
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_agent_runtime.adapters.runtime_tables import run_checkpoint_writes, run_checkpoints
from dw_kernel.errors import TenantContextMissingError

_SET_TENANT = text("SELECT set_config('app.tenant_id', :tenant_id, true)")


def _scope(config: RunnableConfig) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, str]:
    conf = config.get("configurable", {})
    thread_id = conf.get("thread_id")
    tenant_id = conf.get("tenant_id")
    workspace_id = conf.get("workspace_id")
    if not thread_id or not tenant_id or not workspace_id:
        raise TenantContextMissingError(
            "checkpoint config requires thread_id, tenant_id and workspace_id"
        )
    return (
        uuid.UUID(str(thread_id)),
        uuid.UUID(str(tenant_id)),
        uuid.UUID(str(workspace_id)),
        str(conf.get("checkpoint_ns", "")),
    )


class SqlAlchemyCheckpointSaver(BaseCheckpointSaver[str]):
    """Async checkpoint persistence with per-transaction RLS context."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        super().__init__(serde=JsonPlusSerializer())
        self._session_factory = session_factory

    async def _session(self, tenant_id: uuid.UUID) -> AsyncSession:
        session = self._session_factory()
        await session.begin()
        await session.execute(_SET_TENANT, {"tenant_id": str(tenant_id)})
        return session

    # ------------------------------------------------------------- reading --
    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        run_id, tenant_id, _, ns = _scope(config)
        wanted_id = config.get("configurable", {}).get("checkpoint_id")

        session = await self._session(tenant_id)
        try:
            query = (
                sa.select(run_checkpoints)
                .where(
                    run_checkpoints.c.run_id == run_id,
                    run_checkpoints.c.checkpoint_ns == ns,
                )
                .order_by(run_checkpoints.c.checkpoint_id.desc())
                .limit(1)
            )
            if wanted_id:
                query = query.where(run_checkpoints.c.checkpoint_id == str(wanted_id))
            row = (await session.execute(query)).first()
            if row is None:
                return None

            writes_rows = (
                await session.execute(
                    sa.select(run_checkpoint_writes)
                    .where(
                        run_checkpoint_writes.c.run_id == run_id,
                        run_checkpoint_writes.c.checkpoint_ns == ns,
                        run_checkpoint_writes.c.checkpoint_id == row.checkpoint_id,
                    )
                    .order_by(run_checkpoint_writes.c.task_id, run_checkpoint_writes.c.idx)
                )
            ).all()
            return self._row_to_tuple(row, writes_rows)
        finally:
            await session.rollback()
            await session.close()

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        if config is None:
            return
        run_id, tenant_id, _, ns = _scope(config)
        session = await self._session(tenant_id)
        try:
            query = (
                sa.select(run_checkpoints)
                .where(
                    run_checkpoints.c.run_id == run_id,
                    run_checkpoints.c.checkpoint_ns == ns,
                )
                .order_by(run_checkpoints.c.checkpoint_id.desc())
            )
            if before is not None:
                before_id = before.get("configurable", {}).get("checkpoint_id")
                if before_id:
                    query = query.where(run_checkpoints.c.checkpoint_id < str(before_id))
            if limit is not None:
                query = query.limit(limit)
            rows = (await session.execute(query)).all()
            for row in rows:
                yield self._row_to_tuple(row, [])
        finally:
            await session.rollback()
            await session.close()

    # ------------------------------------------------------------- writing --
    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        run_id, tenant_id, workspace_id, ns = _scope(config)
        parent_id = config.get("configurable", {}).get("checkpoint_id")

        type_cp, blob_cp = self.serde.dumps_typed(checkpoint)
        _, blob_md = self.serde.dumps_typed(dict(metadata))

        session = await self._session(tenant_id)
        try:
            await session.execute(
                sa.dialects.postgresql.insert(run_checkpoints)
                .values(
                    run_id=run_id,
                    checkpoint_ns=ns,
                    checkpoint_id=checkpoint["id"],
                    parent_checkpoint_id=str(parent_id) if parent_id else None,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    type=type_cp,
                    checkpoint=blob_cp,
                    metadata=blob_md,
                    created_at=sa.func.now(),
                )
                .on_conflict_do_nothing()
            )
            await session.commit()
        finally:
            await session.close()

        return cast(
            RunnableConfig,
            {
                "configurable": {
                    "thread_id": str(run_id),
                    "checkpoint_ns": ns,
                    "checkpoint_id": checkpoint["id"],
                    "tenant_id": str(tenant_id),
                    "workspace_id": str(workspace_id),
                }
            },
        )

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        run_id, tenant_id, workspace_id, ns = _scope(config)
        checkpoint_id = config.get("configurable", {}).get("checkpoint_id")
        if not checkpoint_id:
            raise TenantContextMissingError("aput_writes requires checkpoint_id in config")

        session = await self._session(tenant_id)
        try:
            for idx, (channel, value) in enumerate(writes):
                type_w, blob_w = self.serde.dumps_typed(value)
                await session.execute(
                    sa.dialects.postgresql.insert(run_checkpoint_writes)
                    .values(
                        run_id=run_id,
                        checkpoint_ns=ns,
                        checkpoint_id=str(checkpoint_id),
                        task_id=task_id,
                        idx=idx,
                        tenant_id=tenant_id,
                        workspace_id=workspace_id,
                        channel=channel,
                        type=type_w,
                        value=blob_w,
                        task_path=task_path,
                    )
                    .on_conflict_do_nothing()
                )
            await session.commit()
        finally:
            await session.close()

    async def adelete_thread(self, thread_id: str) -> None:
        # Deletion goes through retention policies (phase 5); runtime never
        # deletes checkpoints on its own.
        raise NotImplementedError("checkpoint deletion is a retention-policy operation")

    # -------------------------------------------------------------- mapping --
    def _row_to_tuple(self, row: Any, writes_rows: Sequence[Any]) -> CheckpointTuple:
        checkpoint = self.serde.loads_typed((row.type, row.checkpoint))
        metadata = self.serde.loads_typed((row.type, row.metadata))
        parent_config: RunnableConfig | None = None
        if row.parent_checkpoint_id:
            parent_config = cast(
                RunnableConfig,
                {
                    "configurable": {
                        "thread_id": str(row.run_id),
                        "checkpoint_ns": row.checkpoint_ns,
                        "checkpoint_id": row.parent_checkpoint_id,
                        "tenant_id": str(row.tenant_id),
                        "workspace_id": str(row.workspace_id),
                    }
                },
            )
        return CheckpointTuple(
            config=cast(
                RunnableConfig,
                {
                    "configurable": {
                        "thread_id": str(row.run_id),
                        "checkpoint_ns": row.checkpoint_ns,
                        "checkpoint_id": row.checkpoint_id,
                        "tenant_id": str(row.tenant_id),
                        "workspace_id": str(row.workspace_id),
                    }
                },
            ),
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=parent_config,
            pending_writes=[
                (w.task_id, w.channel, self.serde.loads_typed((w.type, w.value)))
                for w in writes_rows
            ],
        )
