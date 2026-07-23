"""Tender domain errors built on the kernel taxonomy."""

from __future__ import annotations

from dw_kernel.errors import DomainError


class TenderDomainError(DomainError):
    """Base class for tender-context rule violations."""


class MissingEvidenceError(TenderDomainError):
    """A mandatory criterion cannot be judged compliant without evidence."""


class InvalidScoringConfigError(TenderDomainError):
    """Scoring weights/mandatory flags are inconsistent."""
