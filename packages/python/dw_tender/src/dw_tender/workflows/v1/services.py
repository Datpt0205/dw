"""Dependency bundle for tender workflow nodes (ports only)."""

from __future__ import annotations

from dataclasses import dataclass

from dw_agent_runtime.ports import ModelGateway
from dw_kernel.ports import IdGenerator, UtcClock
from dw_knowledge.ports import KnowledgeGatewayPort
from dw_memory.service import MemoryService
from dw_tender.application.ports import DocumentStoragePort, TenderUnitOfWorkFactory
from dw_tender.domain.services.scoring_engine import ScoringEngine


@dataclass(frozen=True)
class TenderWorkflowServices:
    uow_factory: TenderUnitOfWorkFactory
    storage: DocumentStoragePort
    knowledge: KnowledgeGatewayPort
    model_gateway: ModelGateway
    memory_service: MemoryService
    scoring_engine: ScoringEngine
    clock: UtcClock
    id_generator: IdGenerator
    prompt_bundle_version: str = "1.0.0"
    model_profile: str = "balanced"
    exports_bucket_prefix: str = "exports"
