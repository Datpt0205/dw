"""Knowledge ports. The vector adapter is internal to the gateway package;
business contexts call the gateway, never the vector store."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from dw_knowledge.contracts import EvidenceChunk, SearchQuery
from dw_platform.application.access_context import AccessContext


class KnowledgeGatewayPort(Protocol):
    """The only retrieval entry point available to workflow nodes.

    Implementations MUST inject tenant/workspace/ACL filters derived from
    ``context`` before any vector search is executed.
    """

    async def search(
        self,
        query: SearchQuery,
        context: AccessContext,
    ) -> list[EvidenceChunk]: ...


@dataclass(frozen=True)
class TrustedSearchFilter:
    """Mandatory retrieval constraints derived ONLY from AccessContext.

    Constructed exclusively by the knowledge gateway — adapters must refuse to
    search without one. Callers (and model output) have no way to supply it.
    """

    tenant_id: UUID
    workspace_id: UUID
    domain: str
    allowed_classifications: tuple[str, ...]
    acl_principals: tuple[str, ...]


@dataclass(frozen=True)
class IndexableChunk:
    """A chunk plus the payload metadata required by blueprint §13.3."""

    chunk_id: UUID
    document_id: UUID
    tenant_id: UUID
    workspace_id: UUID
    domain: str
    content: str
    classification: str
    source_version: str
    index_version: str
    provenance_hash: str
    acl_principals: tuple[str, ...]
    vector: tuple[float, ...]


@dataclass(frozen=True)
class VectorHit:
    chunk_id: UUID
    document_id: UUID
    score: float
    content: str
    classification: str
    source_version: str
    provenance_hash: str


class VectorIndexPort(Protocol):
    """Vector store adapter (Qdrant). Search REQUIRES a trusted filter."""

    async def ensure_ready(self, vector_dimension: int) -> None: ...

    async def upsert(self, chunks: Sequence[IndexableChunk]) -> None: ...

    async def search(
        self,
        vector: Sequence[float],
        trusted_filter: TrustedSearchFilter,
        top_k: int,
    ) -> list[VectorHit]: ...


class EmbeddingPort(Protocol):
    """Embedding provider; deterministic hash adapter for local/test."""

    @property
    def dimension(self) -> int: ...

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class ObjectStoragePort(Protocol):
    """Artifact storage (MinIO/S3); keys are tenant-prefixed by the gateway."""

    async def put_object(self, key: str, data: bytes, content_type: str) -> str: ...

    async def get_object(self, key: str) -> bytes: ...
