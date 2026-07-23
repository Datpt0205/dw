"""Audit event: append-only fact record (blueprint §20.5).

Immutability is enforced twice: frozen dataclass here, and the runtime DB role
has no UPDATE/DELETE grant on the audit table.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from dw_kernel.ids import TenantId, UserId, WorkspaceId


@dataclass(frozen=True, slots=True)
class AuditEvent:
    id: uuid.UUID
    tenant_id: TenantId
    workspace_id: WorkspaceId
    actor_id: UserId
    action: str
    resource_type: str
    resource_id: str
    occurred_at: datetime
    run_id: uuid.UUID | None = None
    policy_decision: str | None = None
    trace_id: str | None = None
    details: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.action.strip():
            raise ValueError("audit action must not be blank")
        if self.occurred_at.tzinfo is None:
            raise ValueError("audit occurred_at must be timezone-aware")
