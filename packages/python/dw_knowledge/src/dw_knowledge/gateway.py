"""Knowledge gateway: THE ONLY place tenant/ACL filters are injected (§13.2).

Ingestion: artifact → object storage → chunks (PG) → vectors (Qdrant payload
per §13.3). Retrieval: AccessContext → TrustedSearchFilter → filtered vector
search → evidence pack with provenance.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_kernel.ports import IdGenerator, UtcClock
from dw_knowledge import tables
from dw_knowledge.chunking import chunk_text
from dw_knowledge.contracts import EvidenceChunk, EvidenceRef, SearchQuery
from dw_knowledge.ports import (
    EmbeddingPort,
    IndexableChunk,
    ObjectStoragePort,
    TrustedSearchFilter,
    VectorIndexPort,
)
from dw_platform.application.access_context import AccessContext

_SET_TENANT = text("SELECT set_config('app.tenant_id', :tenant_id, true)")

# Clearance → classifications the caller may read (§15.6, fail closed).
_CLEARANCE_ALLOWS: dict[str, tuple[str, ...]] = {
    "internal": ("internal",),
    "confidential": ("internal", "confidential"),
    "restricted": ("internal", "confidential", "restricted"),
}

INDEX_VERSION = "2026-07-23.1"


class IngestDocumentCommand(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    domain: str = "shared"
    classification: str = "internal"
    source_version: str = "1"
    content_type: str = "text/plain"


@dataclass(frozen=True)
class IngestedDocument:
    document_id: uuid.UUID
    chunk_count: int
    storage_key: str


def build_trusted_filter(context: AccessContext, domain: str) -> TrustedSearchFilter:
    """Derive mandatory constraints from the verified context ONLY."""
    allowed = _CLEARANCE_ALLOWS.get(context.clearance, ("internal",))
    principals = [f"user:{context.principal_id}", "tenant:*"]
    principals.extend(f"role:{role}" for role in sorted(context.roles))
    return TrustedSearchFilter(
        tenant_id=context.tenant_id,
        workspace_id=context.workspace_id,
        domain=domain,
        allowed_classifications=allowed,
        acl_principals=tuple(principals),
    )


@dataclass
class KnowledgeGateway:
    """Implements ``KnowledgeGatewayPort`` + ingestion."""

    session_factory: async_sessionmaker[AsyncSession]
    vector_index: VectorIndexPort
    embeddings: EmbeddingPort
    object_storage: ObjectStoragePort
    clock: UtcClock
    id_generator: IdGenerator
    _ready: bool = field(default=False, init=False)

    async def ensure_ready(self) -> None:
        if not self._ready:
            await self.vector_index.ensure_ready(self.embeddings.dimension)
            self._ready = True

    # ------------------------------------------------------------ ingestion --
    async def ingest_document(
        self, command: IngestDocumentCommand, context: AccessContext
    ) -> IngestedDocument:
        await self.ensure_ready()
        document_id = self.id_generator.new_uuid()
        storage_key = f"{context.tenant_id}/{context.workspace_id}/documents/{document_id}"
        source_uri = await self.object_storage.put_object(
            storage_key, command.content.encode("utf-8"), command.content_type
        )

        text_chunks = chunk_text(command.content)
        chunk_ids = [self.id_generator.new_uuid() for _ in text_chunks]

        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"tenant_id": str(context.tenant_id)})
            await session.execute(
                sa.insert(tables.documents).values(
                    id=document_id,
                    tenant_id=context.tenant_id,
                    workspace_id=context.workspace_id,
                    title=command.title,
                    domain=command.domain,
                    source_uri=source_uri,
                    classification=command.classification,
                    source_version=command.source_version,
                    index_version=INDEX_VERSION,
                    created_by=context.principal_id,
                    created_at=self.clock.now(),
                )
            )
            for chunk, chunk_id in zip(text_chunks, chunk_ids, strict=True):
                await session.execute(
                    sa.insert(tables.chunks).values(
                        id=chunk_id,
                        tenant_id=context.tenant_id,
                        workspace_id=context.workspace_id,
                        document_id=document_id,
                        seq=chunk.seq,
                        content=chunk.content,
                        start_offset=chunk.start_offset,
                        end_offset=chunk.end_offset,
                        provenance_hash=chunk.provenance_hash,
                        metadata={},
                    )
                )

        if text_chunks:
            vectors = await self.embeddings.embed([c.content for c in text_chunks])
            await self.vector_index.upsert(
                [
                    IndexableChunk(
                        chunk_id=chunk_id,
                        document_id=document_id,
                        tenant_id=context.tenant_id,
                        workspace_id=context.workspace_id,
                        domain=command.domain,
                        content=chunk.content,
                        classification=command.classification,
                        source_version=command.source_version,
                        index_version=INDEX_VERSION,
                        provenance_hash=chunk.provenance_hash,
                        acl_principals=("tenant:*",),
                        vector=tuple(vector),
                    )
                    for chunk, chunk_id, vector in zip(text_chunks, chunk_ids, vectors, strict=True)
                ]
            )
        return IngestedDocument(
            document_id=document_id,
            chunk_count=len(text_chunks),
            storage_key=storage_key,
        )

    # ------------------------------------------------------------ retrieval --
    async def search(self, query: SearchQuery, context: AccessContext) -> list[EvidenceChunk]:
        trusted_filter = build_trusted_filter(context, query.domain)
        vector = (await self.embeddings.embed([query.text]))[0]
        hits = await self.vector_index.search(vector, trusted_filter, query.top_k)

        evidence: list[EvidenceChunk] = []
        for hit in hits:
            if hit.score < query.min_relevance:
                continue
            if query.document_ids and hit.document_id not in query.document_ids:
                continue
            evidence.append(
                EvidenceChunk(
                    content=hit.content,
                    evidence=EvidenceRef(
                        evidence_id=self.id_generator.new_uuid(),
                        source_document_id=hit.document_id,
                        source_version=hit.source_version,
                        chunk_id=hit.chunk_id,
                        quote=hit.content[:280],
                        relevance_score=max(0.0, min(1.0, hit.score)),
                        classification=hit.classification,
                        provenance_hash=hit.provenance_hash,
                    ),
                )
            )
        return evidence
