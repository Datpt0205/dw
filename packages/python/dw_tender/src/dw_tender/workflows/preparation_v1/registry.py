"""Registers the DW01 preparation graph with the shared GraphRegistry."""

from __future__ import annotations

from dw_agent_runtime.registry import GraphRegistry
from dw_tender.workflows.preparation_v1.graph import GRAPH_VERSION, build_preparation_graph
from dw_tender.workflows.preparation_v1.services import PreparationServices

WORKER_ID = "preparation"


def register_preparation_graphs(
    registry: GraphRegistry, services: PreparationServices
) -> None:
    registry.register(WORKER_ID, GRAPH_VERSION, lambda: build_preparation_graph(services))
