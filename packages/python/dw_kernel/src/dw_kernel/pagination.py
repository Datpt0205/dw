"""Cursor pagination primitives shared by list queries."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field

_MAX_PAGE_SIZE = 200
_DEFAULT_PAGE_SIZE = 50


@dataclass(frozen=True, slots=True)
class Cursor:
    """Opaque continuation token; payload is context-defined."""

    token: str

    @classmethod
    def encode(cls, raw: str) -> Cursor:
        return cls(base64.urlsafe_b64encode(raw.encode()).decode())

    def decode(self) -> str:
        try:
            return base64.urlsafe_b64decode(self.token.encode()).decode()
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise ValueError("invalid cursor token") from exc


@dataclass(frozen=True, slots=True)
class PageRequest:
    size: int = _DEFAULT_PAGE_SIZE
    cursor: Cursor | None = None

    def __post_init__(self) -> None:
        if not 1 <= self.size <= _MAX_PAGE_SIZE:
            raise ValueError(f"page size must be in [1, {_MAX_PAGE_SIZE}], got {self.size}")


@dataclass(frozen=True)
class Page[T]:
    items: list[T] = field(default_factory=list)
    next_cursor: Cursor | None = None

    @property
    def has_more(self) -> bool:
        return self.next_cursor is not None
