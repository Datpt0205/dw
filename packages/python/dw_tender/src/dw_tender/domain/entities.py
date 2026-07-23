"""Tender domain entities (blueprint §4.3, §19.3)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_tender.domain.exceptions import TenderDomainError
from dw_tender.domain.value_objects.ids import RequirementId, TenderCaseId
from dw_tender.domain.value_objects.scoring import RequirementKind


class CaseStatus(StrEnum):
    CREATED = "created"
    ANALYZING = "analyzing"
    RECOMMENDATION_READY = "recommendation_ready"
    COMPLETED = "completed"


class DocumentKind(StrEnum):
    RFQ = "rfq"
    SUPPLIER_SUBMISSION = "supplier_submission"
    OTHER = "other"


class FindingStatus(StrEnum):
    COMPLIANT = "compliant"
    NON_COMPLIANT = "non_compliant"
    MISSING_EVIDENCE = "missing_evidence"


@dataclass(slots=True)
class TenderCase:
    id: TenderCaseId
    tenant_id: TenantId
    workspace_id: WorkspaceId
    title: str
    created_by: UserId
    description: str = ""
    status: CaseStatus = CaseStatus.CREATED
    last_run_id: uuid.UUID | None = None
    export_ref: str | None = None
    version: int = 1

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise TenderDomainError("case title must not be blank")

    def start_analysis(self, run_id: uuid.UUID) -> None:
        self.status = CaseStatus.ANALYZING
        self.last_run_id = run_id
        self.version += 1

    def mark_recommendation_ready(self) -> None:
        self.status = CaseStatus.RECOMMENDATION_READY
        self.version += 1

    def complete(self, export_ref: str) -> None:
        if not export_ref.strip():
            raise TenderDomainError("export_ref must not be blank")
        self.status = CaseStatus.COMPLETED
        self.export_ref = export_ref
        self.version += 1


@dataclass(frozen=True, slots=True)
class TenderDocument:
    id: uuid.UUID
    tenant_id: TenantId
    workspace_id: WorkspaceId
    case_id: TenderCaseId
    kind: DocumentKind
    title: str
    storage_key: str
    content_hash: str
    supplier_name: str | None = None
    knowledge_document_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        if self.kind is DocumentKind.SUPPLIER_SUBMISSION and not (self.supplier_name or "").strip():
            raise TenderDomainError("supplier submissions require a supplier_name")


@dataclass(frozen=True, slots=True)
class Requirement:
    id: RequirementId
    tenant_id: TenantId
    workspace_id: WorkspaceId
    case_id: TenderCaseId
    code: str
    statement: str
    kind: RequirementKind
    weight: Decimal

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise TenderDomainError("requirement code must not be blank")
        if self.kind is RequirementKind.WEIGHTED and self.weight <= 0:
            raise TenderDomainError(f"weighted requirement {self.code} needs weight > 0")
        if self.kind is not RequirementKind.WEIGHTED and self.weight != 0:
            raise TenderDomainError(f"non-weighted requirement {self.code} must have weight 0")


@dataclass(frozen=True, slots=True)
class ComplianceFinding:
    id: uuid.UUID
    tenant_id: TenantId
    workspace_id: WorkspaceId
    case_id: TenderCaseId
    requirement_code: str
    supplier_name: str
    status: FindingStatus
    raw_score: Decimal
    note: str = ""
    evidence: tuple[dict[str, object], ...] = ()  # serialized EvidenceRef dicts

    def __post_init__(self) -> None:
        if not Decimal(0) <= self.raw_score <= Decimal(100):
            raise TenderDomainError("raw_score must be within [0, 100]")


@dataclass(slots=True)
class TenderRecommendation:
    id: uuid.UUID
    tenant_id: TenantId
    workspace_id: WorkspaceId
    case_id: TenderCaseId
    scoring_policy_version: str
    recommended_supplier: str | None = None
    rationale: str = ""
    supplier_scores: list[dict[str, object]] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    evidence: list[dict[str, object]] = field(default_factory=list)
    gate_passed: bool = False
    gate_violations: list[str] = field(default_factory=list)
    confidence: float = 0.0
