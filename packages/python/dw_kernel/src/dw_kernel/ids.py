"""Identifier value objects shared across bounded contexts.

Only truly universal identifiers live here (see blueprint §7.2). Context-specific
identifiers (MeetingId, TenderCaseId, ...) are defined inside their own context.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Self


@dataclass(frozen=True, slots=True)
class EntityId:
    """Base value object wrapping a UUID identity."""

    value: uuid.UUID

    @classmethod
    def from_string(cls, raw: str) -> Self:
        try:
            return cls(uuid.UUID(raw))
        except ValueError as exc:
            raise ValueError(f"{cls.__name__} requires a valid UUID, got {raw!r}") from exc

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class TenantId(EntityId):
    """Identifies a tenant (customer organization)."""


@dataclass(frozen=True, slots=True)
class WorkspaceId(EntityId):
    """Identifies a workspace inside a tenant."""


@dataclass(frozen=True, slots=True)
class UserId(EntityId):
    """Identifies a platform user (principal)."""


@dataclass(frozen=True, slots=True)
class RunId(EntityId):
    """Identifies a single worker run."""
