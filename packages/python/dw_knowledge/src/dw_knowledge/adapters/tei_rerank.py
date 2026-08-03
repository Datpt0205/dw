"""BGE-reranker-v2-m3 cross-encoder reranking via a TEI ``/rerank`` endpoint.

Implements ``RerankPort``. Runs on CPU in the ``tei-rerank`` container so the
4GB GPU stays free for embeddings.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import httpx

from dw_kernel.errors import InfrastructureError
from dw_knowledge.ports import RerankCandidate, RerankResult


@dataclass
class TeiRerankAdapter:
    """Implements ``RerankPort`` against a TEI reranker server."""

    base_url: str
    timeout: float = 60.0

    async def rerank(
        self, query: str, candidates: Sequence[RerankCandidate], top_k: int
    ) -> list[RerankResult]:
        if not candidates:
            return []
        texts = [c.text for c in candidates]
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/rerank",
                    json={"query": query, "texts": texts, "return_text": False},
                )
                resp.raise_for_status()
                data = resp.json()  # [{"index": i, "score": s}, ...] sorted desc
        except httpx.HTTPError as exc:
            raise InfrastructureError(
                "TEI rerank request failed", details={"error": type(exc).__name__}
            ) from exc
        results: list[RerankResult] = []
        for row in data[:top_k]:
            idx = int(row["index"])
            if 0 <= idx < len(candidates):
                results.append(RerankResult(id=candidates[idx].id, score=float(row["score"])))
        return results
