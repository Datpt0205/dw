"""WorkOps state graph v1 (blueprint §11.1) — pure wiring, no business logic."""

from __future__ import annotations

from itertools import pairwise

from langgraph.graph import END, START, StateGraph

from dw_work_ops.workflows.v1.nodes import WorkOpsNodes
from dw_work_ops.workflows.v1.services import WorkOpsWorkflowServices
from dw_work_ops.workflows.v1.state import WorkOpsState

GRAPH_VERSION = "1.1.0"  # 1.1.0: + analyze_meeting (grounded quality analysis)

_NODE_ORDER = (
    "ingest_transcript",
    "normalize_transcript",
    "resolve_speakers",
    "summarize_meeting",
    "analyze_meeting",
    "extract_decisions",
    "extract_action_items",
    "resolve_assignees",
    "validate_due_dates",
    "enrich_with_org_context",
    "policy_gate",
    "human_review",
    "dispatch_tasks",
    "track_and_follow_up",
    "close_and_write_memory",
)


def build_work_ops_graph(services: WorkOpsWorkflowServices) -> StateGraph:  # type: ignore[type-arg]
    nodes = WorkOpsNodes(services)
    graph: StateGraph = StateGraph(WorkOpsState)  # type: ignore[type-arg]
    for name in _NODE_ORDER:
        graph.add_node(name, getattr(nodes, name))
    graph.add_edge(START, _NODE_ORDER[0])
    for previous, current in pairwise(_NODE_ORDER):
        graph.add_edge(previous, current)
    graph.add_edge(_NODE_ORDER[-1], END)
    return graph
