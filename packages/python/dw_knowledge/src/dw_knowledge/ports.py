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
    # Enterprise-RAG metadata (Phase A): outline breadcrumb + global order so a
    # split passage can be reassembled and cited (see chunking.structure_aware_chunks).
    section_path: str = ""
    seq: int = 0
    scope: str = "tenant"  # "tenant" | "global" (legal docs shared across tenants — Phase B)


@dataclass(frozen=True)
class ParsedDocument:
    """Output of a DocumentParser: extracted text + detected metadata.

    Phase A ships a plaintext/markdown parser; Phase B adds a Docling adapter for
    PDF/DOCX/XLSX/scanned (OCR) with table-aware extraction behind this same port.
    """

    text: str
    detected_title: str | None = None
    page_count: int | None = None
    warnings: tuple[str, ...] = ()


class DocumentParserPort(Protocol):
    """Turns an uploaded file (bytes) into clean UTF-8 text + metadata."""

    def supports(self, content_type: str, filename: str) -> bool: ...

    async def parse(self, data: bytes, content_type: str, filename: str) -> ParsedDocument: ...


@dataclass(frozen=True)
class RerankCandidate:
    id: str
    text: str


@dataclass(frozen=True)
class RerankResult:
    id: str
    score: float


class RerankPort(Protocol):
    """Cross-encoder reranker seam (Phase B: BGE-reranker via TEI). No-op default."""

    async def rerank(
        self, query: str, candidates: Sequence[RerankCandidate], top_k: int
    ) -> list[RerankResult]: ...


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

    async def delete_document(self, document_id: UUID) -> None:
        """HARD-remove all points of a document (same-version reindex / purge)."""
        ...

    async def tombstone_document(self, document_id: UUID) -> None:
        """SOFT-delete: mark a document's points is_deleted=true so search skips
        them, but keep them for traceability until a retention purge."""
        ...

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
