"""Registers Tender graph versions into the runtime graph registry."""

from __future__ import annotations

from dw_agent_runtime.registry import GraphRegistry
from dw_tender.workflows.v1.graph import GRAPH_VERSION, build_tender_graph
from dw_tender.workflows.v1.services import TenderWorkflowServices

WORKER_ID = "tender"


def register_tender_graphs(registry: GraphRegistry, services: TenderWorkflowServices) -> None:
    registry.register(WORKER_ID, GRAPH_VERSION, lambda: build_tender_graph(services))
