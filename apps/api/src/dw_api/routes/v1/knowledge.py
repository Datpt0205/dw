"""Knowledge inventory API (read-only; ingestion happens inside workflows)."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Query
from pydantic import BaseModel

from dw_api.dependencies.auth import RequireAccessContext
from dw_api.dependencies.services import RequireContainer
from dw_kernel.errors import InfrastructureError


class KnowledgeDocumentView(BaseModel):
    document_id: uuid.UUID
    title: str
    domain: str
    classification: str
    source_version: str
    index_version: str | None
    chunk_count: int
    created_at: datetime


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
        )
        for doc in documents
    ]
