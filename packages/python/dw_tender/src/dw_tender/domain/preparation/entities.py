"""DW01 domain: the ProcurementPreparationCase aggregate + versioned artifacts.

DW01 turns an approved purchase request into an official solicitation package:
intake -> procurement approach (CP1) -> solicitation package (CP2) -> official.
The aggregate owns its state machine; deterministic gates (application layer)
decide transitions, the LLM only drafts content.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
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
    COMPLETED = "completed"
    FAILED = "failed"


class ArtifactType(StrEnum):
    DEMAND_SNAPSHOT = "demand_snapshot"
    COMPLETENESS_REPORT = "completeness_report"
    CLARIFICATION_LIST = "clarification_list"
    PROCUREMENT_APPROACH = "procurement_approach"
    SOLICITATION_PACKAGE = "solicitation_package"
    EVALUATION_CRITERIA = "evaluation_criteria"
    SUPPLIER_SHORTLIST = "supplier_shortlist"
    RISK_COMPLIANCE_CHECK = "risk_compliance_check"
    OFFICIAL_PACKAGE_MANIFEST = "official_package_manifest"


class ArtifactStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    OFFICIAL = "official"


class DocumentKind(StrEnum):
    APPROVED_PR = "approved_pr"
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
    method_key: str | None = None
    state: CaseState = CaseState.DRAFT
    current_step: str = "intake"
    last_run_id: uuid.UUID | None = None
    current_official_artifact_id: uuid.UUID | None = None
    export_ref: str | None = None
    version: int = 1

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise TenderDomainError("preparation case title must not be blank")

    def mark_intake_ready(self) -> None:
        self.state = CaseState.INTAKE_READY
        self.current_step = "intake"
        self.version += 1

    def start_run(self, run_id: uuid.UUID) -> None:
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
