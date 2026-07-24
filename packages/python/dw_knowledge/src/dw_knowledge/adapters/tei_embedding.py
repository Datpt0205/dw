"""BGE-M3 dense embeddings via a Text-Embeddings-Inference (TEI) HTTP endpoint.

Implements ``EmbeddingPort``. The model runs in the ``tei-embed`` container; this
adapter just calls its ``/embed`` API, so no ML deps enter the app image.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import httpx

from dw_kernel.errors import InfrastructureError

_BATCH = 32


@dataclass
class TeiEmbeddingAdapter:
    """Implements ``EmbeddingPort`` against a TEI server (BGE-M3, dim 1024)."""

    base_url: str
    _dimension: int = 1024
    timeout: float = 120.0

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        out: list[list[float]] = []
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                for start in range(0, len(texts), _BATCH):
                    batch = list(texts[start : start + _BATCH])
                    resp = await client.post(
                        f"{self.base_url}/embed",
                        json={"inputs": batch, "normalize": True},
                    )
                    resp.raise_for_status()
                    out.extend(resp.json())
        except httpx.HTTPError as exc:
            raise InfrastructureError(
                "TEI embedding request failed", details={"error": type(exc).__name__}
            ) from exc
        return out
