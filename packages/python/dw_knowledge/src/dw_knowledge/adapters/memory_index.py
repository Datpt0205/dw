"""In-memory vector index (working adapter for local/test without Qdrant).

Implements the SAME trusted-filter semantics as the Qdrant adapter — tenant,
workspace, classification, ACL and domain constraints all apply. Not durable:
suitable only for tests and infra-less local runs (never production).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from dw_knowledge.ports import IndexableChunk, TrustedSearchFilter, VectorHit


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


@dataclass
class InMemoryVectorIndexAdapter:
    """Implements ``VectorIndexPort`` in process memory."""

    _chunks: dict[str, IndexableChunk] = field(default_factory=dict)

    async def ensure_ready(self, vector_dimension: int) -> None:
        return None

    async def upsert(self, chunks: Sequence[IndexableChunk]) -> None:
        for chunk in chunks:
            self._chunks[str(chunk.chunk_id)] = chunk

    async def search(
        self,
        vector: Sequence[float],
        trusted_filter: TrustedSearchFilter,
        top_k: int,
    ) -> list[VectorHit]:
        principals = set(trusted_filter.acl_principals)
        allowed = set(trusted_filter.allowed_classifications)
        hits: list[VectorHit] = []
        for chunk in self._chunks.values():
            if chunk.tenant_id != trusted_filter.tenant_id:
                continue
            if chunk.workspace_id != trusted_filter.workspace_id:
                continue
            if chunk.classification not in allowed:
                continue
            if not (set(chunk.acl_principals) & principals):
                continue
            if trusted_filter.domain != "shared" and chunk.domain not in (
                trusted_filter.domain,
                "shared",
            ):
                continue
            hits.append(
                VectorHit(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    score=_cosine(vector, chunk.vector),
                    content=chunk.content,
                    classification=chunk.classification,
                    source_version=chunk.source_version,
                    provenance_hash=chunk.provenance_hash,
                )
            )
        hits.sort(key=lambda h: -h.score)
        return hits[:top_k]
