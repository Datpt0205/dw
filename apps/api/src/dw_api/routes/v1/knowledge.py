"""Knowledge inventory + upload API.

Retrieval/ingestion internals live in the gateway; this router only exposes the
tenant-safe surface: list documents, upload (async ingest via the worker queue),
check an ingest job, and soft-delete a document.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, File, Form, Query, UploadFile
from pydantic import BaseModel

from dw_api.dependencies.auth import RequireAccessContext
from dw_api.dependencies.services import RequireContainer
from dw_kernel.errors import (
    DomainError,
    InfrastructureError,
    NotFoundError,
    PermissionDeniedError,
)
from dw_knowledge.ingest_jobs import EnqueueIngestCommand

# Documents up to this size are accepted for ingestion (raw bytes staged to
# object storage). Larger files should use a pre-signed multipart flow (future).
_MAX_UPLOAD_BYTES = 50 * 1024 * 1024
_PLATFORM_ADMIN_ROLE = "platform_admin"


class KnowledgeDocumentView(BaseModel):
    document_id: uuid.UUID
    title: str
    domain: str
    classification: str
    source_version: str
    index_version: str | None
    chunk_count: int
    created_at: datetime
    scope: str


class IngestJobView(BaseModel):
    job_id: uuid.UUID
    status: str
    title: str
    filename: str
    scope: str
    attempts: int
    error: str | None
    document_id: uuid.UUID | None
    chunk_count: int | None
    created_at: datetime
    updated_at: datetime


router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("/documents", response_model=list[KnowledgeDocumentView])
async def list_documents(
    context: RequireAccessContext,
    container: RequireContainer,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[KnowledgeDocumentView]:
    if container.knowledge_gateway is None:
        raise InfrastructureError("knowledge gateway is not configured")
    await container.authorization.require(
        context=context, action="knowledge.read", resource_type="knowledge_document"
    )
    documents = await container.knowledge_gateway.list_documents(context, limit=limit)
    return [
        KnowledgeDocumentView(
            document_id=doc.document_id,
            title=doc.title,
            domain=doc.domain,
            classification=doc.classification,
            source_version=doc.source_version,
            index_version=doc.index_version,
            chunk_count=doc.chunk_count,
            created_at=doc.created_at,
            scope=doc.scope,
        )
        for doc in documents
    ]


@router.post("/documents", response_model=IngestJobView, status_code=202)
async def upload_document(
    context: RequireAccessContext,
    container: RequireContainer,
    file: UploadFile = File(...),
    title: str = Form(...),
    domain: str = Form("shared"),
    classification: str = Form("internal"),
    source_version: str = Form("1"),
    scope: str = Form("tenant"),
) -> IngestJobView:
    if container.ingest_job_store is None or container.object_storage is None:
        raise InfrastructureError("knowledge ingestion is not configured")
    await container.authorization.require(
        context=context, action="knowledge.write", resource_type="knowledge_document"
    )
    # Publishing a GLOBAL (cross-tenant legal) document is a platform-admin act:
    # a tenant member must not seed content every other tenant can read.
    if scope not in ("tenant", "global"):
        raise DomainError("scope must be 'tenant' or 'global'")
    if scope == "global" and _PLATFORM_ADMIN_ROLE not in context.roles:
        raise PermissionDeniedError("publishing a global document requires platform_admin")

    data = await file.read()
    if not data:
        raise DomainError("uploaded file is empty")
    if len(data) > _MAX_UPLOAD_BYTES:
        raise DomainError(f"file exceeds {_MAX_UPLOAD_BYTES} bytes")

    filename = file.filename or "document"
    content_type = file.content_type or "application/octet-stream"
    job_id = container.ingest_job_store.id_generator.new_uuid()
    # Stage the raw bytes; the worker reads them back by storage_key to parse.
    storage_key = f"{context.tenant_id}/{context.workspace_id}/uploads/{job_id}/{filename}"
    await container.object_storage.put_object(storage_key, data, content_type)

    command = EnqueueIngestCommand(
        title=title,
        filename=filename,
        content_type=content_type,
        domain=domain,
        classification=classification,
        source_version=source_version,
        scope=scope,
    )
    # Reuse the pre-generated id so the staged object and the job line up.
    created = await container.ingest_job_store.enqueue(
        command, context, storage_key=storage_key, job_id=job_id
    )
    job = await container.ingest_job_store.get(created, context)
    assert job is not None
    return _job_view(job)


@router.get("/documents/jobs/{job_id}", response_model=IngestJobView)
async def get_ingest_job(
    job_id: uuid.UUID,
    context: RequireAccessContext,
    container: RequireContainer,
) -> IngestJobView:
    if container.ingest_job_store is None:
        raise InfrastructureError("knowledge ingestion is not configured")
    await container.authorization.require(
        context=context, action="knowledge.read", resource_type="knowledge_document"
    )
    job = await container.ingest_job_store.get(job_id, context)
    if job is None:
        raise NotFoundError("ingest job not found")
    return _job_view(job)


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(
    document_id: uuid.UUID,
    context: RequireAccessContext,
    container: RequireContainer,
) -> None:
    if container.knowledge_gateway is None:
        raise InfrastructureError("knowledge gateway is not configured")
    await container.authorization.require(
        context=context, action="knowledge.write", resource_type="knowledge_document"
    )
    await container.knowledge_gateway.soft_delete_document(document_id, context)


def _job_view(job) -> IngestJobView:  # type: ignore[no-untyped-def]
    return IngestJobView(
        job_id=job.id,
        status=job.status,
        title=job.title,
        filename=job.filename,
        scope=job.scope,
        attempts=job.attempts,
        error=job.error,
        document_id=job.document_id,
        chunk_count=job.chunk_count,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )
