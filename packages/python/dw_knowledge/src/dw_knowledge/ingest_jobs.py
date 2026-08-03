"""Durable ingest-job queue (B5).

The API ``enqueue``s a job (raw file already in object storage) and returns 202;
the worker ``claim_next``s one, runs parse→chunk→embed→index via the gateway, then
``mark_done``/``mark_failed``. Tenant isolation is enforced by RLS: enqueue/get run
under ``app.tenant_id``; the cross-tenant drain scan runs under ``app.worker_drain``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_kernel.ports import IdGenerator, UtcClock
from dw_knowledge import tables
from dw_platform.application.access_context import AccessContext

_SET_TENANT = text("SELECT set_config('app.tenant_id', :tenant_id, true)")
_SET_WORKER_DRAIN = text("SELECT set_config('app.worker_drain', 'on', true)")


class EnqueueIngestCommand(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    content_type: str = "application/octet-stream"
    domain: str = "shared"
    classification: str = "internal"
    source_version: str = "1"
    scope: str = "tenant"


@dataclass(frozen=True)
class IngestJob:
    id: uuid.UUID
    tenant_id: uuid.UUID
    workspace_id: uuid.UUID
    created_by: uuid.UUID
    title: str
    domain: str
    classification: str
    source_version: str
    scope: str
    filename: str
    content_type: str
    storage_key: str
    status: str
    attempts: int
    error: str | None
    document_id: uuid.UUID | None
    chunk_count: int | None
    created_at: datetime
    updated_at: datetime


def _row_to_job(row: sa.Row[Any]) -> IngestJob:
    return IngestJob(
        id=row.id,
        tenant_id=row.tenant_id,
        workspace_id=row.workspace_id,
        created_by=row.created_by,
        title=row.title,
        domain=row.domain,
        classification=row.classification,
        source_version=row.source_version,
        scope=row.scope,
        filename=row.filename,
        content_type=row.content_type,
        storage_key=row.storage_key,
        status=row.status,
        attempts=row.attempts,
        error=row.error,
        document_id=row.document_id,
        chunk_count=row.chunk_count,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@dataclass
class IngestJobStore:
    """CRUD over ``knowledge.ingest_jobs`` with RLS-correct tenant context."""

    session_factory: async_sessionmaker[AsyncSession]
    clock: UtcClock
    id_generator: IdGenerator

    async def enqueue(
        self,
        command: EnqueueIngestCommand,
        context: AccessContext,
        *,
        storage_key: str,
        job_id: uuid.UUID | None = None,
    ) -> uuid.UUID:
        job_id = job_id or self.id_generator.new_uuid()
        now = self.clock.now()
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"tenant_id": str(context.tenant_id)})
            await session.execute(
                sa.insert(tables.ingest_jobs).values(
                    id=job_id,
                    tenant_id=context.tenant_id,
                    workspace_id=context.workspace_id,
                    created_by=context.principal_id,
                    title=command.title,
                    domain=command.domain,
                    classification=command.classification,
                    source_version=command.source_version,
                    scope=command.scope,
                    filename=command.filename,
                    content_type=command.content_type,
                    storage_key=storage_key,
                    status="queued",
                    attempts=0,
                    created_at=now,
                    updated_at=now,
                )
            )
        return job_id

    async def get(self, job_id: uuid.UUID, context: AccessContext) -> IngestJob | None:
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"tenant_id": str(context.tenant_id)})
            row = (
                await session.execute(
                    sa.select(tables.ingest_jobs).where(tables.ingest_jobs.c.id == job_id)
                )
            ).one_or_none()
            return _row_to_job(row) if row is not None else None

    async def claim_next(self) -> IngestJob | None:
        """Atomically move the oldest queued job to ``processing`` and return it.

        Uses ``FOR UPDATE SKIP LOCKED`` so concurrent workers never grab the same
        row. The cross-tenant scan is authorised by the ``app.worker_drain`` GUC;
        the claiming UPDATE runs under the job's own ``app.tenant_id``.
        """
        now = self.clock.now()
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_WORKER_DRAIN)
            row = (
                await session.execute(
                    sa.select(tables.ingest_jobs)
                    .where(tables.ingest_jobs.c.status == "queued")
                    .order_by(tables.ingest_jobs.c.created_at.asc())
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
            ).one_or_none()
            if row is None:
                return None
            # The claiming UPDATE must satisfy tenant_isolation → set app.tenant_id.
            await session.execute(_SET_TENANT, {"tenant_id": str(row.tenant_id)})
            await session.execute(
                sa.update(tables.ingest_jobs)
                .where(tables.ingest_jobs.c.id == row.id)
                .values(status="processing", attempts=row.attempts + 1, updated_at=now)
            )
            return _row_to_job(row)

    async def mark_done(self, job: IngestJob, *, document_id: uuid.UUID, chunk_count: int) -> None:
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"tenant_id": str(job.tenant_id)})
            await session.execute(
                sa.update(tables.ingest_jobs)
                .where(tables.ingest_jobs.c.id == job.id)
                .values(
                    status="done",
                    document_id=document_id,
                    chunk_count=chunk_count,
                    error=None,
                    updated_at=self.clock.now(),
                )
            )

    async def mark_failed(self, job: IngestJob, *, error: str) -> None:
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"tenant_id": str(job.tenant_id)})
            await session.execute(
                sa.update(tables.ingest_jobs)
                .where(tables.ingest_jobs.c.id == job.id)
                .values(status="failed", error=error[:2000], updated_at=self.clock.now())
            )
