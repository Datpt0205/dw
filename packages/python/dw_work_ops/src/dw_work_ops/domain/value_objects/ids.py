"""Work-ops context identifiers, private to this context."""

from __future__ import annotations

from dataclasses import dataclass

from dw_kernel.ids import EntityId


@dataclass(frozen=True, slots=True)
class MeetingId(EntityId):
    """Identifies a meeting session aggregate."""


@dataclass(frozen=True, slots=True)
class TranscriptArtifactId(EntityId):
    """Identifies an uploaded transcript artifact."""


@dataclass(frozen=True, slots=True)
class ActionItemId(EntityId):
    """Identifies an action item."""
