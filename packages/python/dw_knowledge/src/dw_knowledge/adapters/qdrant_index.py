"""Qdrant vector index adapter (ADR-006: payload multitenancy + tenant index).

Search is impossible without a TrustedSearchFilter — the filter argument is not
optional and the tenant/workspace conditions are always appended here from it,
never from caller-supplied values.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from qdrant_client import AsyncQdrantClient, models

from dw_kernel.errors import InfrastructureError
from dw_knowledge.ports import IndexableChunk, TrustedSearchFilter, VectorHit

DEFAULT_COLLECTION = "dw_knowledge"


@dataclass
class QdrantVectorIndexAdapter:
    """Implements ``VectorIndexPort``."""

    client: AsyncQdrantClient
    collection: str = DEFAULT_COLLECTION

    async def ensure_ready(self, vector_dimension: int) -> None:
        try:
            if await self.client.collection_exists(self.collection):
                info = await self.client.get_collection(self.collection)
                current = info.config.params.vectors
                size = getattr(current, "size", None)
                if size == vector_dimension:
                    return
                # Embedding model changed (e.g. hash 64 -> BGE-M3 1024): recreate.
                await self.client.delete_collection(self.collection)
            await self.client.create_collection(
                collection_name=self.collection,
                vectors_config=models.VectorParams(
                    size=vector_dimension, distance=models.Distance.COSINE
                ),
                # Scalar quantization keeps RAM/latency low on modest hardware.
                quantization_config=models.ScalarQuantization(
                    scalar=models.ScalarQuantizationConfig(
                        type=models.ScalarType.INT8, always_ram=True
                    )
                ),
            )
            # Tenant-optimized index (blueprint §13.3, ADR-006).
            await self.client.create_payload_index(
                self.collection,
                field_name="tenant_id",
                field_schema=models.KeywordIndexParams(
                    type=models.KeywordIndexType.KEYWORD, is_tenant=True
                ),
            )
            for field in ("workspace_id", "domain", "classification", "acl_principals"):
                await self.client.create_payload_index(
                    self.collection,
                    field_name=field,
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )
            await self.client.create_payload_index(
                self.collection,
                field_name="is_deleted",
                field_schema=models.PayloadSchemaType.BOOL,
            )
        except Exception as exc:
            raise InfrastructureError(
                "failed to prepare Qdrant collection",
                details={"collection": self.collection, "error": type(exc).__name__},
            ) from exc

    async def upsert(self, chunks: Sequence[IndexableChunk]) -> None:
        if not chunks:
            return
        points = [
            models.PointStruct(
                id=str(chunk.chunk_id),
                vector=list(chunk.vector),
                payload={
                    "tenant_id": str(chunk.tenant_id),
                    "workspace_id": str(chunk.workspace_id),
                    "domain": chunk.domain,
                    "resource_id": str(chunk.document_id),
                    "source_document_id": str(chunk.document_id),
                    "chunk_id": str(chunk.chunk_id),
                    "acl_principals": list(chunk.acl_principals),
                    "classification": chunk.classification,
                    "source_version": chunk.source_version,
                    "index_version": chunk.index_version,
                    "provenance_hash": chunk.provenance_hash,
                    "content": chunk.content,
                    "section_path": chunk.section_path,
                    "seq": chunk.seq,
                    "scope": chunk.scope,
                    "is_deleted": False,
                },
            )
            for chunk in chunks
        ]
        try:
            await self.client.upsert(self.collection, points=points, wait=True)
        except Exception as exc:
            raise InfrastructureError(
                "failed to upsert vectors", details={"error": type(exc).__name__}
            ) from exc

    def _document_filter(self, document_id: uuid.UUID) -> models.Filter:
        return models.Filter(
            must=[
                models.FieldCondition(
                    key="source_document_id",
                    match=models.MatchValue(value=str(document_id)),
                )
            ]
        )

    async def delete_document(self, document_id: uuid.UUID) -> None:
        try:
            await self.client.delete(
                self.collection,
                points_selector=models.FilterSelector(filter=self._document_filter(document_id)),
                wait=True,
            )
        except Exception as exc:
            raise InfrastructureError(
                "failed to delete document vectors", details={"error": type(exc).__name__}
            ) from exc

    async def tombstone_document(self, document_id: uuid.UUID) -> None:
        try:
            await self.client.set_payload(
                self.collection,
                payload={"is_deleted": True},
                points=models.FilterSelector(filter=self._document_filter(document_id)),
                wait=True,
            )
        except Exception as exc:
            raise InfrastructureError(
                "failed to tombstone document vectors", details={"error": type(exc).__name__}
            ) from exc

    async def search(
        self,
        vector: Sequence[float],
        trusted_filter: TrustedSearchFilter,
        top_k: int,
    ) -> list[VectorHit]:
        # Mandatory constraints come EXCLUSIVELY from the trusted filter.
        conditions: list[models.FieldCondition] = [
            models.FieldCondition(
                key="classification",
                match=models.MatchAny(any=list(trusted_filter.allowed_classifications)),
            ),
            models.FieldCondition(
                key="acl_principals",
                match=models.MatchAny(any=list(trusted_filter.acl_principals)),
            ),
        ]
        if trusted_filter.domain != "shared":
            conditions.append(
                models.FieldCondition(
                    key="domain",
                    match=models.MatchAny(any=[trusted_filter.domain, "shared"]),
                )
            )
        # Tenant isolation OR global (legal) scope: a point is visible if it is in
        # the caller's tenant+workspace, OR it is a cross-tenant global document.
        own_tenant = models.Filter(
            must=[
                models.FieldCondition(
                    key="tenant_id",
                    match=models.MatchValue(value=str(trusted_filter.tenant_id)),
                ),
                models.FieldCondition(
                    key="workspace_id",
                    match=models.MatchValue(value=str(trusted_filter.workspace_id)),
                ),
            ]
        )
        scope_or_tenant = [
            own_tenant,
            models.FieldCondition(key="scope", match=models.MatchValue(value="global")),
        ]
        try:
            response = await self.client.query_points(
                self.collection,
                query=list(vector),
                query_filter=models.Filter(
                    must=list(conditions),
                    should=scope_or_tenant,  # at least one → (own tenant) OR (global)
                    # Soft-deleted / superseded points are never retrieved.
                    must_not=[
                        models.FieldCondition(
                            key="is_deleted", match=models.MatchValue(value=True)
                        )
                    ],
                ),
                limit=top_k,
                with_payload=True,
            )
        except Exception as exc:
            raise InfrastructureError(
                "vector search failed", details={"error": type(exc).__name__}
            ) from exc

        hits: list[VectorHit] = []
        for point in response.points:
            payload = point.payload or {}
            hits.append(
                VectorHit(
                    chunk_id=_uuid(payload.get("chunk_id")),
                    document_id=_uuid(payload.get("source_document_id")),
                    score=float(point.score),
                    content=str(payload.get("content", "")),
                    classification=str(payload.get("classification", "internal")),
                    source_version=str(payload.get("source_version", "1")),
                    provenance_hash=str(payload.get("provenance_hash", "")),
                )
            )
        return hits


def _uuid(value: object) -> uuid.UUID:
    return uuid.UUID(str(value))
