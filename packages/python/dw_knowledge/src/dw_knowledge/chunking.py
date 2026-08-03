"""Deterministic text chunking with overlap. Same input → same chunks.

Two levels:
- ``chunk_text`` — flat window chunking (kept for callers that don't need structure).
- ``structure_aware_chunks`` — enterprise chunking: detects the document outline
  (Phần/Chương/Mục/Điều, or markdown headings), keeps each section as a *parent*
  and splits long sections into *leaf* chunks that carry ``section_path`` and a
  global ``seq`` order. Leaves are the retrieval unit; the parent section gives
  context (small-to-big). A leaf that is part of a split passage still knows its
  predecessor via ``seq`` (prev = seq-1 in the same document) and its parent via
  ``section_index`` — so continuity is recoverable at read time.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class TextChunk:
    seq: int
    start_offset: int
    end_offset: int
    content: str

    @property
    def provenance_hash(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Section:
    """A parent node in the document outline (e.g. one Điều / one heading)."""

    index: int
    path: str  # breadcrumb, e.g. "Chương II > Điều 15"
    level: int
    start_offset: int
    end_offset: int
    content: str


@dataclass(frozen=True, slots=True)
class LeafChunk:
    """A retrieval-unit chunk. Ordering = (document, seq); parent = section_index."""

    seq: int
    section_index: int
    section_path: str
    start_offset: int
    end_offset: int
    content: str

    @property
    def contextual_text(self) -> str:
        """Text used for EMBEDDING — section breadcrumb prepended so the chunk is
        self-contained even when a passage is split (Anthropic contextual retrieval).
        The raw ``content`` is stored unchanged for display/citation."""
        return f"[{self.section_path}]\n{self.content}" if self.section_path else self.content

    @property
    def provenance_hash(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ChunkingResult:
    sections: list[Section] = field(default_factory=list)
    chunks: list[LeafChunk] = field(default_factory=list)


_HEADING_PREFIXES: tuple[tuple[str, int], ...] = (
    ("phần ", 1),
    ("chương ", 2),
    ("mục ", 3),
    ("điều ", 4),
)


def _heading_level(line: str) -> int | None:
    """Return the outline level of a heading line, or None if it isn't a heading."""
    s = line.strip()
    if not s:
        return None
    if s.startswith("#"):  # markdown heading
        return min(len(s) - len(s.lstrip("#")), 6)
    low = s.lower()
    for prefix, level in _HEADING_PREFIXES:
        if low.startswith(prefix) and any(ch.isdigit() or ch in "IVXLCDM" for ch in s[:24]):
            return level
    return None


def _split_section(
    text: str,
    sec_start: int,
    sec_end: int,
    seq_start: int,
    section_index: int,
    path: str,
    *,
    max_chars: int,
    overlap_chars: int,
) -> list[LeafChunk]:
    """Window-split one section's span into leaf chunks with global offsets."""
    leaves: list[LeafChunk] = []
    seq = seq_start
    start = sec_start
    while start < sec_end:
        end = min(start + max_chars, sec_end)
        if end < sec_end:
            for separator in ("\n\n", "\n", ". ", " "):
                candidate = text.rfind(separator, start + max_chars // 2, end)
                if candidate != -1:
                    end = candidate + len(separator)
                    break
        content = text[start:end].strip()
        if content:
            leaves.append(
                LeafChunk(
                    seq=seq,
                    section_index=section_index,
                    section_path=path,
                    start_offset=start,
                    end_offset=end,
                    content=content,
                )
            )
            seq += 1
        if end >= sec_end:
            break
        start = max(end - overlap_chars, start + 1)
    return leaves


def structure_aware_chunks(
    text: str,
    *,
    max_chars: int = 1200,
    overlap_chars: int = 150,
) -> ChunkingResult:
    """Outline-aware, parent-child chunking. Deterministic and offset-preserving."""
    if max_chars <= 0 or overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError("require max_chars > 0 and 0 <= overlap_chars < max_chars")
    if not text.strip():
        return ChunkingResult()

    # 1) Find heading boundaries (offset, level, title).
    headings: list[tuple[int, int, str]] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        level = _heading_level(line)
        if level is not None:
            headings.append((offset, level, line.strip().lstrip("#").strip()))
        offset += len(line)

    # 2) Build sections spanning the text; maintain a breadcrumb stack by level.
    sections: list[Section] = []
    if not headings:
        sections.append(Section(0, "", 0, 0, len(text), text))
    else:
        if headings[0][0] > 0:  # preamble before first heading
            sections.append(Section(0, "Mở đầu", 0, 0, headings[0][0], text[: headings[0][0]]))
        stack: list[tuple[int, str]] = []
        for i, (h_off, level, title) in enumerate(headings):
            end = headings[i + 1][0] if i + 1 < len(headings) else len(text)
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            path = " > ".join(t for _, t in stack)
            sections.append(Section(len(sections), path, level, h_off, end, text[h_off:end]))

    # 3) Split each section into ordered leaf chunks (global seq).
    chunks: list[LeafChunk] = []
    seq = 0
    for section in sections:
        leaves = _split_section(
            text,
            section.start_offset,
            section.end_offset,
            seq,
            section.index,
            section.path,
            max_chars=max_chars,
            overlap_chars=overlap_chars,
        )
        chunks.extend(leaves)
        seq += len(leaves)
    return ChunkingResult(sections=sections, chunks=chunks)


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
