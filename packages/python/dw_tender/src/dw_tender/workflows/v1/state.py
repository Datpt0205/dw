"""Typed, versioned graph state for the Tender agent (blueprint §12.3).

Checkpointed — JSON-serializable values only.
"""

from __future__ import annotations

from typing import Any, TypedDict

STATE_SCHEMA_VERSION = "1.0"


class TenderState(TypedDict, total=False):
    schema_version: str
    case_id: str
    document_texts: dict[str, str]  # tender document id -> raw text
    document_meta: dict[str, dict[str, Any]]  # id -> {kind, title, supplier_name, hash}
    requirements: list[dict[str, Any]]
    matrix_suppliers: list[str]
    policy_evidence: list[dict[str, Any]]  # retrieval evidence pack (EvidenceRef dicts)
    assessed_findings: list[dict[str, Any]]
    risks: list[str]
    draft_recommendation: dict[str, Any]
    gate_result: dict[str, Any]
    approval_payload: dict[str, Any]
    approval_decision: dict[str, Any]
    export_ref: str
    memory_written: bool
    warnings: list[str]
