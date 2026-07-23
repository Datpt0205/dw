"""Tender boundary DTOs: LLM output schemas + API views."""

from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from dw_tender.domain.entities import (
    ComplianceFinding,
    Requirement,
    TenderCase,
    TenderRecommendation,
)

# ------------------------------------------------------- LLM output schemas --


class ExtractedRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=r"^REQ-\d{2}$")
    statement: str = Field(min_length=1)
    kind: str = Field(pattern=r"^(mandatory|weighted|informational)$")
    weight: float = Field(ge=0, le=1)


class ExtractedRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirements: list[ExtractedRequirement] = Field(default_factory=list)


class AssessedFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_name: str = Field(min_length=1)
    requirement_code: str = Field(pattern=r"^REQ-\d{2}$")
    claimed_compliant: bool
    raw_score: float = Field(ge=0, le=100)
    quote: str = ""
    note: str = ""


class ComplianceAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[AssessedFinding] = Field(default_factory=list)


class RecommendationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommended_supplier: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


# ---------------------------------------------------------------- API views --


class RequirementView(BaseModel):
    id: uuid.UUID
    code: str
    statement: str
    kind: str
    weight: str

    @classmethod
    def from_domain(cls, requirement: Requirement) -> RequirementView:
        return cls(
            id=requirement.id.value,
            code=requirement.code,
            statement=requirement.statement,
            kind=requirement.kind.value,
            weight=str(requirement.weight),
        )


class FindingView(BaseModel):
    requirement_code: str
    supplier_name: str
    status: str
    raw_score: str
    note: str
    evidence_count: int
    quote: str | None

    @classmethod
    def from_domain(cls, finding: ComplianceFinding) -> FindingView:
        quote = None
        if finding.evidence:
            first = finding.evidence[0]
            quote = str(first.get("quote")) if first.get("quote") else None
        return cls(
            requirement_code=finding.requirement_code,
            supplier_name=finding.supplier_name,
            status=finding.status.value,
            raw_score=str(Decimal(finding.raw_score)),
            note=finding.note,
            evidence_count=len(finding.evidence),
            quote=quote,
        )


class RecommendationView(BaseModel):
    recommended_supplier: str | None
    rationale: str
    supplier_scores: list[dict[str, object]]
    risks: list[str]
    gate_passed: bool
    gate_violations: list[str]
    scoring_policy_version: str
    confidence: float
    evidence_count: int

    @classmethod
    def from_domain(cls, rec: TenderRecommendation) -> RecommendationView:
        return cls(
            recommended_supplier=rec.recommended_supplier,
            rationale=rec.rationale,
            supplier_scores=rec.supplier_scores,
            risks=rec.risks,
            gate_passed=rec.gate_passed,
            gate_violations=rec.gate_violations,
            scoring_policy_version=rec.scoring_policy_version,
            confidence=rec.confidence,
            evidence_count=len(rec.evidence),
        )


class TenderCaseView(BaseModel):
    id: uuid.UUID
    title: str
    description: str
    status: str
    last_run_id: uuid.UUID | None
    export_ref: str | None
    requirements: list[RequirementView] = Field(default_factory=list)
    findings: list[FindingView] = Field(default_factory=list)
    recommendation: RecommendationView | None = None

    @classmethod
    def from_domain(
        cls,
        case: TenderCase,
        requirements: list[Requirement],
        findings: list[ComplianceFinding],
        recommendation: TenderRecommendation | None,
    ) -> TenderCaseView:
        return cls(
            id=case.id.value,
            title=case.title,
            description=case.description,
            status=case.status.value,
            last_run_id=case.last_run_id,
            export_ref=case.export_ref,
            requirements=[RequirementView.from_domain(r) for r in requirements],
            findings=[FindingView.from_domain(f) for f in findings],
            recommendation=(
                RecommendationView.from_domain(recommendation) if recommendation else None
            ),
        )
