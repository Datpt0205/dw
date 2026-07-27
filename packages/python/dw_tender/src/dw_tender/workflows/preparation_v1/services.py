"""Dependency bundle for the DW01 preparation graph nodes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dw_agent_runtime.ports import ModelGateway
from dw_kernel.ports import IdGenerator, UtcClock
from dw_knowledge.ports import KnowledgeGatewayPort
from dw_tender.application.ports import DocumentStoragePort
from dw_tender.application.preparation.ports import PreparationUnitOfWorkFactory
from dw_tender.application.preparation.rules import ProcurementRules


@dataclass(frozen=True)
class PreparationServices:
    """Ports-only bundle passed to ``PreparationNodes``.

    Drafting is deterministic (rule-pack + template) in the POC; a model gateway
    can be plugged into the draft_* nodes later without touching the graph.

    ``knowledge`` (optional) grounds the draft_* nodes with retrieved legal /
    policy / template evidence (RAG). When absent, drafting degrades gracefully
    to the rule-pack output with no citations.
    """

    uow_factory: PreparationUnitOfWorkFactory
    storage: DocumentStoragePort
    rules: ProcurementRules
    suppliers: tuple[dict[str, Any], ...]
    clock: UtcClock
    id_generator: IdGenerator
    knowledge: KnowledgeGatewayPort | None = None
    # Optional LLM: powers requirement extraction from the free-text PR. When
    # absent (or on failure), the node falls back to deterministic line parsing.
    model_gateway: ModelGateway | None = None
    model_profile: str = "balanced"
    prompt_bundle_version: str = "1.0.0"
    schema_version: str = "1.0"
    exports_bucket_prefix: str = "exports"
