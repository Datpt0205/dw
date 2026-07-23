import hashlib
import uuid

import pytest

from dw_knowledge.contracts import EvidenceRef
from dw_memory.contracts import MemoryType, WriteDecision
from dw_memory.policy import MemoryCandidate, MemoryWritePolicy

pytestmark = pytest.mark.unit


def make_evidence() -> EvidenceRef:
    return EvidenceRef(
        evidence_id=uuid.uuid4(),
        source_document_id=uuid.uuid4(),
        source_version="1",
        relevance_score=0.9,
        classification="internal",
        provenance_hash=hashlib.sha256(b"evidence").hexdigest(),
    )


def make_candidate(**overrides: object) -> MemoryCandidate:
    defaults: dict[str, object] = {
        "worker_id": "work_ops",
        "memory_type": MemoryType.COMMITMENT,
        "content": "Phòng Kỹ thuật cam kết bàn giao API trước 15/08.",
        "provenance_refs": (make_evidence(),),
        "confidence": 0.9,
        "classification": "internal",
    }
    defaults.update(overrides)
    return MemoryCandidate.model_validate(defaults)


def test_no_provenance_is_rejected() -> None:
    policy = MemoryWritePolicy()
    outcome = policy.evaluate(make_candidate(provenance_refs=()))
    assert outcome.decision is WriteDecision.REJECT
    assert "provenance" in outcome.reason


def test_restricted_always_reviewed() -> None:
    outcome = MemoryWritePolicy().evaluate(
        make_candidate(classification="restricted", confidence=0.99)
    )
    assert outcome.decision is WriteDecision.REVIEW


def test_confident_evidenced_auto_writes() -> None:
    outcome = MemoryWritePolicy().evaluate(make_candidate(confidence=0.85))
    assert outcome.decision is WriteDecision.AUTO_WRITE


def test_mid_confidence_goes_to_review() -> None:
    outcome = MemoryWritePolicy().evaluate(make_candidate(confidence=0.6))
    assert outcome.decision is WriteDecision.REVIEW


def test_low_confidence_rejected() -> None:
    outcome = MemoryWritePolicy().evaluate(make_candidate(confidence=0.2))
    assert outcome.decision is WriteDecision.REJECT
