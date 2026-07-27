"""DW01 domain: the ProcurementPreparationCase aggregate + versioned artifacts.

DW01 turns an approved purchase request into an official solicitation package:
intake -> procurement approach (CP1) -> solicitation package (CP2) -> official.
The aggregate owns its state machine; deterministic gates (application layer)
decide transitions, the LLM only drafts content.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_tender.domain.exceptions import TenderDomainError
from dw_tender.domain.value_objects.ids import (
    ArtifactId,
    PreparationCaseId,
    PreparationDocumentId,
)


class CaseState(StrEnum):
    DRAFT = "draft"
    INTAKE_REJECTED = "intake_rejected"
    INTAKE_READY = "intake_ready"
    ANALYZING = "analyzing"
    WAITING_CLARIFICATION = "waiting_clarification"
    APPROACH_READY = "approach_ready"
    CP1_PENDING = "cp1_pending"
    CP1_REJECTED = "cp1_rejected"
    CP1_APPROVED = "cp1_approved"
    BUILDING_SOLICITATION = "building_solicitation"
    PACKAGE_READY = "package_ready"
    CP2_PENDING = "cp2_pending"
    CP2_REJECTED = "cp2_rejected"
    CP2_APPROVED = "cp2_approved"
    PACKAGE_OFFICIAL = "package_official"
    PUBLISHED = "published"
    CP3_PENDING = "cp3_pending"
    RECEIVING_BIDS = "receiving_bids"
    CP4_READY = "cp4_ready"
    COMPLETED = "completed"
    FAILED = "failed"


class ArtifactType(StrEnum):
    INTAKE_VERIFICATION = "intake_verification"
    SUPPLIER_INPUT = "supplier_input"
    DEMAND_SNAPSHOT = "demand_snapshot"
    COMPLETENESS_REPORT = "completeness_report"
    CLARIFICATION_LIST = "clarification_list"
    CLARIFICATION_RESPONSE = "clarification_response"
    PROCUREMENT_APPROACH = "procurement_approach"
    SOLICITATION_PACKAGE = "solicitation_package"
    EVALUATION_CRITERIA = "evaluation_criteria"
    SUPPLIER_SHORTLIST = "supplier_shortlist"
    RISK_COMPLIANCE_CHECK = "risk_compliance_check"
    OFFICIAL_PACKAGE_MANIFEST = "official_package_manifest"
    PUBLICATION_RECORD = "publication_record"
    ADDENDUM_DRAFT = "addendum_draft"
    ADDENDUM_DECISION = "addendum_decision"
    SUBMISSION_REGISTER = "submission_register"
    BID_OPENING_RECORD = "bid_opening_record"
    EVALUATION_HANDOFF = "evaluation_handoff"


class ArtifactStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    OFFICIAL = "official"


class DocumentKind(StrEnum):
    APPROVED_PR = "approved_pr"
    PUBLICATION_RECEIPT = "publication_receipt"
    ADDENDUM = "addendum"
    SUPPLIER_SUBMISSION = "supplier_submission"
    BID_OPENING_MINUTES = "bid_opening_minutes"
    OTHER = "other"


class ProcurementType(StrEnum):
    """Legal/operating shape of the procurement package."""

    GOODS = "goods"
    CONSTRUCTION = "construction"
    CONSULTING = "consulting"
    NON_CONSULTING = "non_consulting"
    MIXED = "mixed"
    INVESTOR_SELECTION = "investor_selection"
    OTHER = "other"


class BusinessDomain(StrEnum):
    """Business sector used for routing, reporting and knowledge retrieval."""

    GENERAL = "general"
    INFORMATION_TECHNOLOGY = "information_technology"
    REAL_ESTATE = "real_estate"
    HEALTHCARE = "healthcare"
    INFRASTRUCTURE = "infrastructure"
    OPERATIONS = "operations"
    ENERGY = "energy"
    EDUCATION = "education"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class PreparationDocument:
    """An uploaded source document (e.g. the approved PR)."""

    id: PreparationDocumentId
    tenant_id: TenantId
    workspace_id: WorkspaceId
    case_id: PreparationCaseId
    kind: DocumentKind
    title: str
    filename: str
    content_type: str
    size_bytes: int
    storage_key: str
    content_hash: str
    uploaded_by: UserId


@dataclass(frozen=True, slots=True)
class PreparationArtifact:
    """One typed, versioned artifact produced during preparation."""

    id: ArtifactId
    tenant_id: TenantId
    workspace_id: WorkspaceId
    case_id: PreparationCaseId
    artifact_type: ArtifactType
    schema_version: str
    artifact_version: int
    status: ArtifactStatus
    content: dict[str, object]
    created_by: UserId
    evidence_refs: tuple[str, ...] = ()
    source_artifact_ids: tuple[str, ...] = ()
    content_hash: str = ""


@dataclass(slots=True)
class PreparationCase:
    """DW01 aggregate: an approved need being turned into a solicitation package."""

    id: PreparationCaseId
    tenant_id: TenantId
    workspace_id: WorkspaceId
    title: str
    created_by: UserId
    source_pr_ref: str = ""
    description: str = ""
    estimated_value_minor: int = 0
    currency: str = "VND"
    deadline: str | None = None
    owner_name: str = ""
    procurement_type: ProcurementType = ProcurementType.OTHER
    business_domain: BusinessDomain = BusinessDomain.GENERAL
    method_key: str | None = None
    state: CaseState = CaseState.DRAFT
    current_step: str = "intake"
    last_run_id: uuid.UUID | None = None
    current_official_artifact_id: uuid.UUID | None = None
    export_ref: str | None = None
    intake_verified_by: UserId | None = None
    intake_verified_at: datetime | None = None
    version: int = 1

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise TenderDomainError("preparation case title must not be blank")

    def verify_intake(self, verified_by: UserId, verified_at: datetime) -> None:
        if verified_by == self.created_by:
            raise TenderDomainError("case creator cannot verify their own intake")
        if self.state is not CaseState.DRAFT:
            raise TenderDomainError("only a draft case can be intake-verified")
        self.intake_verified_by = verified_by
        self.intake_verified_at = verified_at
        self.state = CaseState.INTAKE_READY
        self.current_step = "intake"
        self.version += 1

    def reject_intake(self, rejected_by: UserId) -> None:
        if rejected_by == self.created_by:
            raise TenderDomainError("case creator cannot reject their own intake")
        if self.state is not CaseState.DRAFT:
            raise TenderDomainError("only a draft case can be intake-rejected")
        self.state = CaseState.INTAKE_REJECTED
        self.current_step = "intake"
        self.version += 1

    def start_run(self, run_id: uuid.UUID) -> None:
        if self.state not in {CaseState.INTAKE_READY, CaseState.WAITING_CLARIFICATION}:
            raise TenderDomainError(f"case cannot run from state {self.state.value}")
        self.state = CaseState.ANALYZING
        self.current_step = "analyzing"
        self.last_run_id = run_id
        self.version += 1

    def advance(self, state: CaseState, step: str, method_key: str | None = None) -> None:
        """Move to a new state (deterministic gates/workflow drive this)."""
        self.state = state
        self.current_step = step
        if method_key is not None:
            self.method_key = method_key
        self.version += 1

    def lock_official(self, artifact_id: uuid.UUID, export_ref: str) -> None:
        if not export_ref.strip():
            raise TenderDomainError("export_ref must not be blank")
        self.state = CaseState.PACKAGE_OFFICIAL
        self.current_step = "official"
        self.current_official_artifact_id = artifact_id
        self.export_ref = export_ref
        self.version += 1

    def complete(self) -> None:
        self.state = CaseState.COMPLETED
        self.current_step = "completed"
        self.version += 1

    def record_publication(self) -> None:
        if self.state is not CaseState.PACKAGE_OFFICIAL:
            raise TenderDomainError("only an official package can be published")
        self.state = CaseState.PUBLISHED
        self.current_step = "publication"
        self.version += 1

    def record_submission(self) -> None:
        if self.state not in {CaseState.PUBLISHED, CaseState.RECEIVING_BIDS}:
            raise TenderDomainError("case is not accepting supplier submissions")
        self.state = CaseState.RECEIVING_BIDS
        self.current_step = "submissions"
        self.version += 1

    def submit_addendum(self) -> None:
        if self.state is not CaseState.PUBLISHED:
            raise TenderDomainError("addendum can only be raised after publication")
        self.state = CaseState.CP3_PENDING
        self.current_step = "cp3"
        self.version += 1

    def resolve_cp3(self) -> None:
        if self.state is not CaseState.CP3_PENDING:
            raise TenderDomainError("case is not waiting for CP3")
        self.state = CaseState.PUBLISHED
        self.current_step = "publication"
        self.version += 1

    def mark_cp4_ready(self) -> None:
        if self.state is not CaseState.RECEIVING_BIDS:
            raise TenderDomainError("case has no supplier submissions to open")
        self.state = CaseState.CP4_READY
        self.current_step = "cp4"
        self.version += 1

    def complete_cp4_handoff(self) -> None:
        if self.state is not CaseState.RECEIVING_BIDS:
            raise TenderDomainError("case has no supplier submissions to hand off")
        self.state = CaseState.COMPLETED
        self.current_step = "completed"
        self.version += 1

    def reopen_after_clarification(self) -> None:
        if self.state is not CaseState.WAITING_CLARIFICATION:
            raise TenderDomainError("case is not waiting for clarification")
        self.state = CaseState.INTAKE_READY
        self.current_step = "intake"
        self.version += 1


# Artifacts whose presence is required before submitting each checkpoint.
CP1_REQUIRED_ARTIFACTS = (
    ArtifactType.DEMAND_SNAPSHOT,
    ArtifactType.COMPLETENESS_REPORT,
    ArtifactType.PROCUREMENT_APPROACH,
)
CP2_REQUIRED_ARTIFACTS = (
    ArtifactType.SOLICITATION_PACKAGE,
    ArtifactType.EVALUATION_CRITERIA,
    ArtifactType.SUPPLIER_SHORTLIST,
    ArtifactType.RISK_COMPLIANCE_CHECK,
)
