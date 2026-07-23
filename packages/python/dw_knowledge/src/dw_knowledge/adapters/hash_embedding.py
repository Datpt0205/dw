"""Deterministic hash-based embedding (local/test adapter, ADR-012).

Not semantic — token hashes bucketed into a fixed-dimension vector, normalized.
Identical text → identical vector, similar wording → nearby vectors. Enough
for exercising filtered retrieval and evidence flows without a provider.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

_TOKEN_PATTERN = re.compile(r"[\w]+", re.UNICODE)


@dataclass(frozen=True)
class HashEmbeddingAdapter:
    """Implements ``EmbeddingPort`` deterministically."""

    _dimension: int = 64

    @property
    def dimension(self) -> int:
        return self._dimension

    def _embed_one(self, content: str) -> list[float]:
        vector = [0.0] * self._dimension
        for token in _TOKEN_PATTERN.findall(content.lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self._dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0.0:
            vector[0] = 1.0
            return vector
        return [v / norm for v in vector]

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]
