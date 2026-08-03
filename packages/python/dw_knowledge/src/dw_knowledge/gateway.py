"""Knowledge gateway: THE ONLY place tenant/ACL filters are injected (§13.2).

Ingestion: artifact → object storage → chunks (PG) → vectors (Qdrant payload
per §13.3). Retrieval: AccessContext → TrustedSearchFilter → filtered vector
search → evidence pack with provenance.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_kernel.ports import IdGenerator, UtcClock
from dw_knowledge import tables
from dw_knowledge.chunking import structure_aware_chunks
from dw_knowledge.contracts import EvidenceChunk, EvidenceRef, SearchQuery
from dw_knowledge.identity import chunk_id_for, doc_key_for, document_id_for
from dw_knowledge.ports import (
    EmbeddingPort,
    IndexableChunk,
    ObjectStoragePort,
    RerankCandidate,
    RerankPort,
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

# Bumped for structure-aware chunking + contextual embedding (Phase A).
INDEX_VERSION = "2026-07-25.structure-1"


class IngestDocumentCommand(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    domain: str = "shared"
    classification: str = "internal"
    source_version: str = "1"
    content_type: str = "text/plain"
    scope: str = "tenant"  # "tenant" | "global" (global RLS/read wired in Phase B)


@dataclass(frozen=True)
class IngestedDocument:
    document_id: uuid.UUID
    chunk_count: int
    storage_key: str


@dataclass(frozen=True)
class DocumentInfo:
    """Read-model row for the knowledge inventory page."""

    document_id: uuid.UUID
    title: str
    domain: str
    classification: str
    source_version: str
    index_version: str | None
    chunk_count: int
    created_at: datetime
    scope: str = "tenant"


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
    reranker: RerankPort | None = None
    # Over-fetch this many x top_k for the reranker to reorder (recall->precision).
    rerank_fetch_multiplier: int = 4
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
        # Deterministic id → re-ingesting the same logical document OVERWRITES it
        # (idempotent), instead of creating a duplicate (see identity.py).
        document_id = document_id_for(
            tenant_id=context.tenant_id,
            workspace_id=context.workspace_id,
            domain=command.domain,
            title=command.title,
            source_version=command.source_version,
            scope=command.scope,
        )
        storage_key = f"{context.tenant_id}/{context.workspace_id}/documents/{document_id}"
        source_uri = await self.object_storage.put_object(
            storage_key, command.content.encode("utf-8"), command.content_type
        )

        # Structure-aware, parent-child chunking; leaves carry section_path + global seq.
        result = structure_aware_chunks(command.content)
        leaves = result.chunks
        chunk_ids = [
            chunk_id_for(document_id=document_id, index_version=INDEX_VERSION, seq=leaf.seq)
            for leaf in leaves
        ]

        doc_key = doc_key_for(
            tenant_id=context.tenant_id,
            workspace_id=context.workspace_id,
            domain=command.domain,
            title=command.title,
            scope=command.scope,
        )
        now = self.clock.now()
        superseded_ids: list[uuid.UUID] = []
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"tenant_id": str(context.tenant_id)})
            # A new version SUPERSEDES the previous current one (kept, not deleted).
            superseded = await session.execute(
                sa.update(tables.documents)
                .where(
                    tables.documents.c.doc_key == doc_key,
                    tables.documents.c.is_current.is_(True),
                    tables.documents.c.id != document_id,
                )
                .values(
                    is_current=False,
                    status="superseded",
                    effective_to=now,
                    superseded_by=document_id,
                )
                .returning(tables.documents.c.id)
            )
            superseded_ids = [row.id for row in superseded]
            if superseded_ids:
                await session.execute(
                    sa.update(tables.chunks)
                    .where(tables.chunks.c.document_id.in_(superseded_ids))
                    .values(status="superseded")
                )
            doc_stmt = pg_insert(tables.documents).values(
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
                created_at=now,
                doc_key=doc_key,
                status="active",
                is_current=True,
                effective_from=now,
                scope=command.scope,
            )
            await session.execute(
                doc_stmt.on_conflict_do_update(
                    index_elements=["id"],
                    set_={
                        "title": doc_stmt.excluded.title,
                        "index_version": doc_stmt.excluded.index_version,
                        "classification": doc_stmt.excluded.classification,
                        "scope": doc_stmt.excluded.scope,
                        # Re-ingesting a previously superseded/deleted version reactivates it.
                        "status": "active",
                        "is_current": True,
                        "effective_to": None,
                        "deleted_at": None,
                        "deleted_by": None,
                    },
                )
            )
            # Replace chunk set (handles shrink on re-ingest).
            await session.execute(
                sa.delete(tables.chunks).where(tables.chunks.c.document_id == document_id)
            )
            for leaf, chunk_id in zip(leaves, chunk_ids, strict=True):
                await session.execute(
                    sa.insert(tables.chunks).values(
                        id=chunk_id,
                        tenant_id=context.tenant_id,
                        workspace_id=context.workspace_id,
                        document_id=document_id,
                        seq=leaf.seq,
                        content=leaf.content,
                        start_offset=leaf.start_offset,
                        end_offset=leaf.end_offset,
                        provenance_hash=leaf.provenance_hash,
                        metadata={
                            "section_path": leaf.section_path,
                            "section_index": leaf.section_index,
                        },
                    )
                )

        # Superseded versions are kept but tombstoned so search skips them.
        for old_id in superseded_ids:
            await self.vector_index.tombstone_document(old_id)
        # Rebuild THIS version's vectors (delete stale then upsert deterministic points).
        await self.vector_index.delete_document(document_id)
        if leaves:
            # Embed the CONTEXTUAL text (breadcrumb prepended) for better retrieval;
            # store raw content for display/citation.
            vectors = await self.embeddings.embed([leaf.contextual_text for leaf in leaves])
            await self.vector_index.upsert(
                [
                    IndexableChunk(
                        chunk_id=chunk_id,
                        document_id=document_id,
                        tenant_id=context.tenant_id,
                        workspace_id=context.workspace_id,
                        domain=command.domain,
                        content=leaf.content,
                        classification=command.classification,
                        source_version=command.source_version,
                        index_version=INDEX_VERSION,
                        provenance_hash=leaf.provenance_hash,
                        acl_principals=("tenant:*",),
                        vector=tuple(vector),
                        section_path=leaf.section_path,
                        seq=leaf.seq,
                        scope=command.scope,
                    )
                    for leaf, chunk_id, vector in zip(leaves, chunk_ids, vectors, strict=True)
                ]
            )
        return IngestedDocument(
            document_id=document_id,
            chunk_count=len(leaves),
            storage_key=storage_key,
        )

    # -------------------------------------------------------------- listing --
    async def list_documents(
        self, context: AccessContext, *, limit: int = 100
    ) -> list[DocumentInfo]:
        """Tenant-scoped document inventory (RLS + explicit workspace filter)."""
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"tenant_id": str(context.tenant_id)})
            rows = await session.execute(
                sa.select(
                    tables.documents,
                    sa.select(sa.func.count())
                    .where(tables.chunks.c.document_id == tables.documents.c.id)
                    .scalar_subquery()
                    .label("chunk_count"),
                )
                .where(
                    # Own workspace OR any global (legal) doc — RLS permits the
                    # cross-tenant read only for scope='global' rows.
                    sa.or_(
                        tables.documents.c.workspace_id == context.workspace_id,
                        tables.documents.c.scope == "global",
                    ),
                    tables.documents.c.status == "active",
                )
                .order_by(tables.documents.c.created_at.desc())
                .limit(limit)
            )
            return [
                DocumentInfo(
                    document_id=row.id,
                    title=row.title,
                    domain=row.domain,
                    classification=row.classification,
                    source_version=row.source_version,
                    index_version=row.index_version,
                    chunk_count=row.chunk_count,
                    created_at=row.created_at,
                    scope=row.scope,
                )
                for row in rows
            ]

    # --------------------------------------------------------- soft delete --
    async def soft_delete_document(self, document_id: uuid.UUID, context: AccessContext) -> None:
        """Tombstone a document (kept for traceability; excluded from retrieval).

        A retention purge (``purge_soft_deleted``) hard-removes it later.
        """
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"tenant_id": str(context.tenant_id)})
            await session.execute(
                sa.update(tables.documents)
                .where(tables.documents.c.id == document_id)
                .values(
                    status="deleted",
                    is_current=False,
                    deleted_at=self.clock.now(),
                    deleted_by=context.principal_id,
                )
            )
            await session.execute(
                sa.update(tables.chunks)
                .where(tables.chunks.c.document_id == document_id)
                .values(status="deleted", deleted_at=self.clock.now())
            )
        await self.vector_index.tombstone_document(document_id)

    async def purge_soft_deleted(self, context: AccessContext, *, before: datetime) -> int:
        """Hard-delete tombstoned rows/points older than ``before`` (worker job).

        Removes from BOTH stores so nothing is orphaned. Returns purge count.
        """
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"tenant_id": str(context.tenant_id)})
            rows = (
                await session.execute(
                    sa.select(tables.documents.c.id).where(
                        tables.documents.c.status.in_(("deleted", "superseded")),
                        sa.or_(
                            tables.documents.c.deleted_at < before,
                            tables.documents.c.effective_to < before,
                        ),
                    )
                )
            ).all()
            doc_ids = [row.id for row in rows]
            if doc_ids:
                await session.execute(
                    sa.delete(tables.chunks).where(tables.chunks.c.document_id.in_(doc_ids))
                )
                await session.execute(
                    sa.delete(tables.documents).where(tables.documents.c.id.in_(doc_ids))
                )
        for doc_id in doc_ids:
            await self.vector_index.delete_document(doc_id)
        return len(doc_ids)

    # ------------------------------------------------------------ retrieval --
    async def search(self, query: SearchQuery, context: AccessContext) -> list[EvidenceChunk]:
        trusted_filter = build_trusted_filter(context, query.domain)
        vector = (await self.embeddings.embed([query.text]))[0]
        # Over-fetch when a reranker is present: dense recall then cross-encoder precision.
        fetch_k = query.top_k * self.rerank_fetch_multiplier if self.reranker else query.top_k
        hits = await self.vector_index.search(vector, trusted_filter, fetch_k)
        if query.document_ids:
            hits = [h for h in hits if h.document_id in query.document_ids]

        rerank_scores: dict[str, float] = {}
        if self.reranker and hits:
            candidates = [RerankCandidate(id=str(h.chunk_id), text=h.content) for h in hits]
            ranked = await self.reranker.rerank(query.text, candidates, query.top_k)
            by_id = {str(h.chunk_id): h for h in hits}
            hits = [by_id[r.id] for r in ranked if r.id in by_id]
            rerank_scores = {r.id: r.score for r in ranked}
        else:
            hits = hits[: query.top_k]

        evidence: list[EvidenceChunk] = []
        for hit in hits:
            score = rerank_scores.get(str(hit.chunk_id), hit.score)
            if score < query.min_relevance:
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
                        relevance_score=max(0.0, min(1.0, score)),
                        classification=hit.classification,
                        provenance_hash=hit.provenance_hash,
                    ),
                )
            )
        return evidence
