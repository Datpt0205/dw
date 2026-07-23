"""Tender state graph v1 (blueprint §12.1) — wiring only."""

from __future__ import annotations

from itertools import pairwise

from langgraph.graph import END, START, StateGraph

from dw_tender.workflows.v1.nodes import TenderNodes
from dw_tender.workflows.v1.services import TenderWorkflowServices
from dw_tender.workflows.v1.state import TenderState

GRAPH_VERSION = "1.0.0"

_NODE_ORDER = (
    "intake_case",
    "parse_documents",
    "classify_documents",
    "extract_requirements",
    "build_requirement_matrix",
    "retrieve_policies_and_history",
    "extract_supplier_responses",
    "score_compliance",
    "identify_gaps_and_risks",
    "draft_recommendation",
    "deterministic_compliance_gate",
    "human_review",
    "export_evaluation_pack",
    "close_and_write_memory",
)


def build_tender_graph(services: TenderWorkflowServices) -> StateGraph:  # type: ignore[type-arg]
    nodes = TenderNodes(services)
    graph: StateGraph = StateGraph(TenderState)  # type: ignore[type-arg]
    for name in _NODE_ORDER:
        graph.add_node(name, getattr(nodes, name))
    graph.add_edge(START, _NODE_ORDER[0])
    for previous, current in pairwise(_NODE_ORDER):
        graph.add_edge(previous, current)
    graph.add_edge(_NODE_ORDER[-1], END)
    return graph
