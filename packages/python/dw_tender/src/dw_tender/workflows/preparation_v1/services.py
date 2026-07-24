"""Dependency bundle for the DW01 preparation graph nodes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dw_kernel.ports import IdGenerator, UtcClock
from dw_tender.application.preparation.ports import PreparationUnitOfWorkFactory
from dw_tender.application.preparation.rules import ProcurementRules
from dw_tender.application.ports import DocumentStoragePort


@dataclass(frozen=True)
class PreparationServices:
    """Ports-only bundle passed to ``PreparationNodes``.

    Drafting is deterministic (rule-pack + template) in the POC; a model gateway
    can be plugged into the draft_* nodes later without touching the graph.
    """

    uow_factory: PreparationUnitOfWorkFactory
    storage: DocumentStoragePort
    rules: ProcurementRules
    suppliers: tuple[dict[str, Any], ...]
    clock: UtcClock
    id_generator: IdGenerator
    schema_version: str = "1.0"
    exports_bucket_prefix: str = "exports"
