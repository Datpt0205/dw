"""DW01 preparation StateGraph: intake -> CP1 -> build -> CP2 -> official.

Mostly linear with two human checkpoints (dynamic ``interrupt`` inside a node)
and two reject branches routed via conditional edges. Returned uncompiled; the
runner compiles it with the SQL checkpointer (durable pause/resume).
"""

from __future__ import annotations

from itertools import pairwise

from langgraph.graph import END, START, StateGraph

from dw_tender.workflows.preparation_v1.nodes import PreparationNodes
from dw_tender.workflows.preparation_v1.services import PreparationServices
from dw_tender.workflows.preparation_v1.state import PreparationState

GRAPH_VERSION = "1.0.0"

_INTAKE_TO_CP1 = (
    "load_case",
    "extract_requirements",
    "completeness_check",
    "draft_procurement_approach",
    "approach_gate",
    "cp1_review",
    "apply_cp1",
)
_CP1_TO_CP2 = (
    "draft_solicitation_package",
    "draft_evaluation_criteria",
    "build_supplier_shortlist",
    "run_risk_check",
    "package_gate",
    "cp2_review",
    "apply_cp2",
)


def _route_after_cp1(state: PreparationState) -> str:
    approved = state.get("cp1_decision", {}).get("approved")
    return "draft_solicitation_package" if approved else "close_failed"


def _route_after_approach_gate(state: PreparationState) -> str:
    if not state.get("approach_gate", {}).get("passed"):
        return "close_incomplete"
    # P6: the gate node pre-fills cp1_decision when delegated autonomy applies —
    # skip the human interrupt and apply the (recorded, auditable) decision.
    if state.get("cp1_decision"):
        return "apply_cp1"
    return "cp1_review"


def _route_after_cp2(state: PreparationState) -> str:
    return "finalize_official" if state.get("cp2_decision", {}).get("approved") else "close_failed"


def build_preparation_graph(services: PreparationServices) -> StateGraph:  # type: ignore[type-arg]
    nodes = PreparationNodes(services)
    graph: StateGraph = StateGraph(PreparationState)  # type: ignore[type-arg]

    all_names = (
        _INTAKE_TO_CP1
        + _CP1_TO_CP2
        + (
            "finalize_official",
            "close_failed",
            "close_incomplete",
        )
    )
    for name in all_names:
        graph.add_node(name, getattr(nodes, name))

    graph.add_edge(START, _INTAKE_TO_CP1[0])
    for previous, current in pairwise(_INTAKE_TO_CP1[:5]):
        graph.add_edge(previous, current)
    graph.add_conditional_edges(
        "approach_gate",
        _route_after_approach_gate,
        {
            "cp1_review": "cp1_review",
            "apply_cp1": "apply_cp1",  # P6 delegated autonomy skips the interrupt
            "close_incomplete": "close_incomplete",
        },
    )
    graph.add_edge("cp1_review", "apply_cp1")

    graph.add_conditional_edges(
        "apply_cp1",
        _route_after_cp1,
        {
            "draft_solicitation_package": "draft_solicitation_package",
            "close_failed": "close_failed",
        },
    )
    for previous, current in pairwise(_CP1_TO_CP2):
        graph.add_edge(previous, current)

    graph.add_conditional_edges(
        "apply_cp2",
        _route_after_cp2,
        {"finalize_official": "finalize_official", "close_failed": "close_failed"},
    )
    graph.add_edge("finalize_official", END)
    graph.add_edge("close_failed", END)
    graph.add_edge("close_incomplete", END)
    return graph
