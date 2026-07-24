"""Tender-context identifiers. These are private to the tender context and
must never be imported by work_ops (enforced by architecture tests)."""

from __future__ import annotations

from dataclasses import dataclass

from dw_kernel.ids import EntityId


@dataclass(frozen=True, slots=True)
class TenderCaseId(EntityId):
    """Identifies a tender case aggregate."""


@dataclass(frozen=True, slots=True)
class RequirementId(EntityId):
    """Identifies an extracted requirement."""


@dataclass(frozen=True, slots=True)
class SupplierId(EntityId):
    """Identifies a supplier."""


@dataclass(frozen=True, slots=True)
class SubmissionId(EntityId):
    """Identifies a supplier submission."""


@dataclass(frozen=True, slots=True)
class PreparationCaseId(EntityId):
    """Identifies a DW01 procurement preparation case aggregate."""


@dataclass(frozen=True, slots=True)
class ArtifactId(EntityId):
    """Identifies a versioned preparation artifact."""


@dataclass(frozen=True, slots=True)
class PreparationDocumentId(EntityId):
    """Identifies an uploaded source document of a preparation case."""
