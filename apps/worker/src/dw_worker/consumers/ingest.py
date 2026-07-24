"""Knowledge ingest consumer: drains the durable upload queue (B5).

Per tick: claim a queued job → fetch the staged bytes → parse (Docling+OCR for
rich formats) → hand the extracted text to the gateway (chunk → embed → index) →
mark done/failed. Parsing runs off the event loop (see DoclingDocumentParser).
"""

from __future__ import annotations

import logging

from dw_knowledge.gateway import IngestDocumentCommand
from dw_knowledge.ingest_jobs import IngestJob
from dw_platform.application.access_context import AccessContext
from dw_worker.composition import IngestComponents

logger = logging.getLogger("dw_worker.ingest")


def _context_for(job: IngestJob) -> AccessContext:
    # A system context scoped to the job's tenant/workspace. The gateway only
    # uses tenant/workspace/principal for storage keys + RLS; no scopes needed.
    return AccessContext(
        tenant_id=job.tenant_id,
        workspace_id=job.workspace_id,
        principal_id=job.created_by,
        roles=frozenset({"system"}),
        scopes=frozenset(),
        clearance="internal",
        plan_id="system",
    )


async def _process(job: IngestJob, components: IngestComponents) -> None:
    data = await components.object_storage.get_object(job.storage_key)
    parsed = await components.parser.parse(data, job.content_type, job.filename)
    if not parsed.text.strip():
        raise ValueError("parser produced empty text")
    result = await components.gateway.ingest_document(
        IngestDocumentCommand(
            title=job.title,
            content=parsed.text,
            domain=job.domain,
            classification=job.classification,
            source_version=job.source_version,
            content_type="text/markdown",
            scope=job.scope,
        ),
        _context_for(job),
    )
    await components.job_store.mark_done(
        job, document_id=result.document_id, chunk_count=result.chunk_count
    )
    logger.info(
        "ingested job=%s document=%s chunks=%d", job.id, result.document_id, result.chunk_count
    )


def build_ingest_consumer(components: IngestComponents, *, batch_size: int = 1):
    """Return a consumer callable draining up to ``batch_size`` jobs per tick."""

    async def consume() -> None:
        for _ in range(batch_size):
            job = await components.job_store.claim_next()
            if job is None:
                return
            try:
                await _process(job, components)
            except Exception as exc:  # record failure, keep draining the queue
                logger.exception("ingest job %s failed", job.id)
                await components.job_store.mark_failed(job, error=f"{type(exc).__name__}: {exc}")

    return consume
