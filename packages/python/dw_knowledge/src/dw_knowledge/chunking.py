"""Deterministic text chunking with overlap. Same input → same chunks."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TextChunk:
    seq: int
    start_offset: int
    end_offset: int
    content: str

    @property
    def provenance_hash(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


def chunk_text(
    text: str,
    *,
    max_chars: int = 1200,
    overlap_chars: int = 150,
) -> list[TextChunk]:
    """Window chunking that prefers paragraph boundaries.

    Deterministic and offset-preserving so evidence can cite exact spans.
    """
    if max_chars <= 0 or overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError("require max_chars > 0 and 0 <= overlap_chars < max_chars")
    stripped = text.strip()
    if not stripped:
        return []

    chunks: list[TextChunk] = []
    start = 0
    seq = 0
    length = len(text)
    while start < length:
        end = min(start + max_chars, length)
        if end < length:
            # Prefer to break on a paragraph, then sentence, then whitespace.
            for separator in ("\n\n", "\n", ". ", " "):
                candidate = text.rfind(separator, start + max_chars // 2, end)
                if candidate != -1:
                    end = candidate + len(separator)
                    break
        content = text[start:end].strip()
        if content:
            chunks.append(TextChunk(seq=seq, start_offset=start, end_offset=end, content=content))
            seq += 1
        if end >= length:
            break
        start = max(end - overlap_chars, start + 1)
    return chunks
