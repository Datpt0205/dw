"""Transactional outbox record (blueprint §7.8, ADR-014).

Written in the same transaction as the aggregate change; the worker process
publishes/executes and marks processed with idempotency.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from dw_kernel.ids import TenantId, WorkspaceId


@dataclass(slots=True)
class OutboxEvent:
    id: uuid.UUID
    tenant_id: TenantId
    workspace_id: WorkspaceId
    event_type: str
    schema_version: str
    aggregate_id: uuid.UUID
    occurred_at: datetime
    payload: dict[str, object] = field(default_factory=dict)
    correlation_id: uuid.UUID | None = None
    causation_id: uuid.UUID | None = None
    actor_id: uuid.UUID | None = None
    processed_at: datetime | None = None
    attempts: int = 0

    def __post_init__(self) -> None:
        if "." not in self.event_type:
            raise ValueError("event_type must be namespaced like 'work_ops.action.dispatched'")

    @property
    def is_processed(self) -> bool:
        return self.processed_at is not None

    def mark_processed(self, at: datetime) -> None:
        if self.processed_at is not None:
            return  # idempotent
        self.processed_at = at

    def record_attempt(self) -> None:
        self.attempts += 1
