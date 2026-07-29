"""Typed, JSON-serialisable state for the DW01 preparation graph (checkpointed)."""

from __future__ import annotations

from typing import Any, TypedDict

STATE_SCHEMA_VERSION = "1.0"


class PreparationState(TypedDict, total=False):
    schema_version: str
    case_id: str
    pr_text: str
    has_approved_pr: bool
    estimated_value_minor: int
    currency: str
    deadline: str | None
    owner_name: str
    case_title: str
    source_pr_ref: str
    procurement_type: str
    business_domain: str

    requirements: list[dict[str, Any]]
    unknowns: list[dict[str, str]]
    clarifications: list[dict[str, Any]]
    clarification_answers: dict[str, str]
    supplier_candidates: list[dict[str, Any]]

    method_key: str
    method_label: str
    min_suppliers: int
    supplier_count_planned: int

    approach_gate: dict[str, Any]
    cp1_payload: dict[str, Any]
    cp1_decision: dict[str, Any]

    criteria: dict[str, Any]
    shortlist: list[dict[str, Any]]
    risk: dict[str, Any]
    package_gate: dict[str, Any]
    cp2_payload: dict[str, Any]
    cp2_decision: dict[str, Any]

    official_manifest: dict[str, Any]
    export_ref: str
    warnings: list[str]
