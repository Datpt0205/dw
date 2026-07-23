"""Base domain event shared by both bounded contexts.

Contexts subclass this with their own event types; the platform outbox
serializes events into the versioned integration envelope (blueprint §16.3).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar

from dw_kernel.ids import TenantId, WorkspaceId


@dataclass(frozen=True, kw_only=True)
class DomainEvent:
    """Immutable fact that happened inside a bounded context."""

    event_type: ClassVar[str] = "kernel.domain_event"
    schema_version: ClassVar[str] = "1.0"

    event_id: uuid.UUID
    occurred_at: datetime
    tenant_id: TenantId
    workspace_id: WorkspaceId
    aggregate_id: uuid.UUID
    correlation_id: uuid.UUID | None = None
    causation_id: uuid.UUID | None = None
    actor_id: uuid.UUID | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.occurred_at.tzinfo is None:
            raise ValueError("DomainEvent.occurred_at must be timezone-aware")
