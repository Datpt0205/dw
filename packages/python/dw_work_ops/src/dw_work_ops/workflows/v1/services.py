"""Dependency bundle injected into workflow nodes.

Nodes receive ONLY ports/services — never SQLAlchemy sessions or provider SDKs
(blueprint §9). The composition root builds this bundle.
"""

from __future__ import annotations

from dataclasses import dataclass

from dw_agent_runtime.executor import ToolExecutor
from dw_agent_runtime.ports import ModelGateway
from dw_kernel.ports import IdGenerator, UtcClock
from dw_memory.service import MemoryService
from dw_work_ops.application.ports import (
    OrganizationDirectoryPort,
    TranscriptStoragePort,
    WorkOpsUnitOfWorkFactory,
)
from dw_work_ops.domain.policies import CanAutoDispatchAction


@dataclass(frozen=True)
class WorkOpsWorkflowServices:
    uow_factory: WorkOpsUnitOfWorkFactory
    storage: TranscriptStoragePort
    directory: OrganizationDirectoryPort
    model_gateway: ModelGateway
    tool_executor: ToolExecutor
    memory_service: MemoryService
    dispatch_policy: CanAutoDispatchAction
    clock: UtcClock
    id_generator: IdGenerator
    prompt_bundle_version: str = "1.0.0"
    model_profile: str = "balanced"
