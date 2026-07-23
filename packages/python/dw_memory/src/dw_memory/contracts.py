"""Memory item schema (blueprint §14.3) with versioned memory schema."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dw_knowledge.contracts import EvidenceRef

MEMORY_SCHEMA_VERSION = "1.0.0"


class MemoryType(StrEnum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
    PREFERENCE = "preference"
    COMMITMENT = "commitment"


class MemoryItem(BaseModel):
    """A single long-term memory fact with provenance and validity window."""

    model_config = ConfigDict(frozen=True)

    memory_id: UUID
    tenant_id: UUID
    workspace_id: UUID
    worker_id: str
    memory_type: MemoryType
    subject_refs: tuple[str, ...] = ()
    content: str = Field(min_length=1)
    structured_facts: dict[str, object] = {}
    provenance_refs: tuple[EvidenceRef, ...] = ()
    confidence: float = Field(ge=0.0, le=1.0)
    classification: str = "internal"
    valid_from: datetime
    valid_until: datetime | None = None
    retention_policy: str = "default"
    memory_schema_version: str = MEMORY_SCHEMA_VERSION
    created_by_run_id: UUID

    @model_validator(mode="after")
    def _validity_window_ordered(self) -> MemoryItem:
        if self.valid_until is not None and self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be after valid_from")
        return self

    def is_valid_at(self, moment: datetime) -> bool:
        if moment < self.valid_from:
            return False
        return self.valid_until is None or moment < self.valid_until


class WriteDecision(StrEnum):
    """Outcome of the memory write policy (§14.2)."""

    AUTO_WRITE = "auto_write"
    REVIEW = "review"
    REJECT = "reject"
