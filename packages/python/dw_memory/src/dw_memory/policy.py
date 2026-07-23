"""Memory write policy (blueprint §14.2): the model never writes directly.

Every candidate is classified; only well-evidenced, sufficiently confident and
appropriately classified facts are auto-written. Everything else waits for
review or is rejected. Fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from dw_knowledge.contracts import EvidenceRef
from dw_memory.contracts import MemoryType, WriteDecision


class MemoryCandidate(BaseModel):
    """A proposed long-term memory fact produced by a workflow."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    worker_id: str
    memory_type: MemoryType
    content: str = Field(min_length=1)
    structured_facts: dict[str, object] = {}
    subject_refs: tuple[str, ...] = ()
    provenance_refs: tuple[EvidenceRef, ...] = ()
    confidence: float = Field(ge=0.0, le=1.0)
    classification: str = "internal"


@dataclass(frozen=True)
class PolicyOutcome:
    decision: WriteDecision
    reason: str


@dataclass(frozen=True)
class MemoryWritePolicy:
    """Versioned policy object; thresholds are configuration, not model output."""

    policy_version: str = "1.0.0"
    auto_write_confidence: float = 0.80
    review_confidence: float = 0.50

    def evaluate(self, candidate: MemoryCandidate) -> PolicyOutcome:
        if not candidate.provenance_refs:
            return PolicyOutcome(WriteDecision.REJECT, "memory without provenance is never stored")
        if candidate.classification == "restricted":
            return PolicyOutcome(
                WriteDecision.REVIEW, "restricted content always requires human review"
            )
        if candidate.confidence >= self.auto_write_confidence:
            return PolicyOutcome(WriteDecision.AUTO_WRITE, "confident, evidenced, unrestricted")
        if candidate.confidence >= self.review_confidence:
            return PolicyOutcome(WriteDecision.REVIEW, "confidence below auto-write threshold")
        return PolicyOutcome(WriteDecision.REJECT, "confidence too low to keep")
