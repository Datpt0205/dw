"""Registers WorkOps graph versions into the runtime graph registry."""

from __future__ import annotations

from dw_agent_runtime.registry import GraphRegistry
from dw_work_ops.workflows.v1.graph import GRAPH_VERSION, build_work_ops_graph
from dw_work_ops.workflows.v1.services import WorkOpsWorkflowServices

WORKER_ID = "work_ops"

# Older graph versions kept resumable: runs checkpointed under these versions
# resolve to the current builder (state is additive-compatible TypedDict).
_COMPAT_VERSIONS = ("1.0.0",)


def register_work_ops_graphs(registry: GraphRegistry, services: WorkOpsWorkflowServices) -> None:
    registry.register(WORKER_ID, GRAPH_VERSION, lambda: build_work_ops_graph(services))
    for version in _COMPAT_VERSIONS:
        registry.register(WORKER_ID, version, lambda: build_work_ops_graph(services))
