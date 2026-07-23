"""Transcript value objects."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    index: int
    speaker: str
    text: str

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValueError("segment index must be >= 0")
        if not self.text.strip():
            raise ValueError("segment text must not be blank")
