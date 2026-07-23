"""Versioned evaluation dataset schema (blueprint §22).

Every worker ships normal/boundary/exception/failure cases plus security cases
(prompt injection, cross-tenant attack, missing evidence, ambiguous identity).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CaseCategory(StrEnum):
    NORMAL = "normal"
    BOUNDARY = "boundary"
    EXCEPTION = "exception"
    FAILURE = "failure"
    PROMPT_INJECTION = "prompt_injection"
    CROSS_TENANT_ATTACK = "cross_tenant_attack"
    MISSING_EVIDENCE = "missing_evidence"
    AMBIGUOUS_IDENTITY = "ambiguous_identity"


SECURITY_CATEGORIES = frozenset(
    {
        CaseCategory.PROMPT_INJECTION,
        CaseCategory.CROSS_TENANT_ATTACK,
        CaseCategory.MISSING_EVIDENCE,
    }
)


class EvalCase(BaseModel):
    """One test case: input fixture reference plus expected outcome reference."""

    model_config = ConfigDict(frozen=True)

    case_id: str = Field(min_length=1)
    category: CaseCategory
    description: str
    input_ref: str
    expected_ref: str
    grader: str = Field(min_length=1)
    tags: frozenset[str] = frozenset()


class EvalDataset(BaseModel):
    """Immutable, versioned dataset for one worker."""

    model_config = ConfigDict(frozen=True)

    dataset_id: str
    dataset_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    worker_id: str
    cases: tuple[EvalCase, ...]

    @field_validator("cases")
    @classmethod
    def _case_ids_unique(cls, cases: tuple[EvalCase, ...]) -> tuple[EvalCase, ...]:
        ids = [case.case_id for case in cases]
        if len(ids) != len(set(ids)):
            raise ValueError("case_id values must be unique within a dataset")
        return cases

    def security_coverage(self) -> frozenset[CaseCategory]:
        """Security categories present; the release gate requires all of them."""
        return frozenset(c.category for c in self.cases) & SECURITY_CATEGORIES

    def has_full_security_coverage(self) -> bool:
        return self.security_coverage() == SECURITY_CATEGORIES
