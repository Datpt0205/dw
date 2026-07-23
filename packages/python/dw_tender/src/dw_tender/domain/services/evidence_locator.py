"""Grounding proposed quotes in source documents (deterministic).

A quote only becomes evidence when it is actually FOUND in the source text —
a model-invented citation yields no evidence and mandatory criteria then fail
closed in the scoring engine.
"""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LocatedQuote:
    start_offset: int
    end_offset: int
    normalized_quote: str
    source_hash: str


def _normalize(text: str) -> str:
    collapsed = " ".join(text.split())
    return unicodedata.normalize("NFC", collapsed).casefold()


def locate_quote(quote: str, source_text: str) -> LocatedQuote | None:
    """Find the quote in the source (whitespace/case tolerant, offset exact)."""
    if not quote.strip():
        return None
    normalized_source = _normalize(source_text)
    normalized_quote = _normalize(quote)
    position = normalized_source.find(normalized_quote)
    if position == -1:
        return None

    # Map normalized position back to raw offsets by walking the raw text.
    raw_offsets: list[int] = []
    previous_space = False
    for index, char in enumerate(source_text):
        if char.isspace():
            if not previous_space and raw_offsets:
                raw_offsets.append(index)
            previous_space = True
        else:
            raw_offsets.append(index)
            previous_space = False
    if position >= len(raw_offsets):
        return None
    start = raw_offsets[position]
    end_index = min(position + len(normalized_quote) - 1, len(raw_offsets) - 1)
    end = raw_offsets[end_index] + 1

    return LocatedQuote(
        start_offset=start,
        end_offset=end,
        normalized_quote=normalized_quote,
        source_hash=hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
    )
