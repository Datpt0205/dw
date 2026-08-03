"""Work-ops domain errors built on the kernel taxonomy."""

from __future__ import annotations

from dw_kernel.errors import DomainError


class WorkOpsDomainError(DomainError):
    """Base class for work-ops rule violations."""


class UnresolvedAssigneeError(WorkOpsDomainError):
    """An action item cannot be dispatched without a resolved assignee."""
