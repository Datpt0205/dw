"""Minimal approval-gated demo graph proving pause/resume semantics.

Not a business workflow — the reference implementation used by runtime tests
and docs. Business graphs live inside their bounded contexts (phase 3/4).
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt


class DemoState(TypedDict, total=False):
    schema_version: str
    subject: str
    prepared_message: str
    approved: bool
    approver_comment: str
    dispatched: bool


def _prepare(state: DemoState) -> DemoState:
    subject = state.get("subject", "")
    return {
        "schema_version": "1.0",
        "prepared_message": f"Prepared action for: {subject}",
    }


def _human_review(state: DemoState) -> DemoState:
    decision: dict[str, Any] = interrupt(
        {
            "approval_type": "demo.dispatch",
            "reason": "demo graph requires human approval before dispatch",
            "prepared_message": state.get("prepared_message", ""),
        }
    )
    return {
        "approved": bool(decision.get("approved")),
        "approver_comment": str(decision.get("comment", "")),
    }


def _dispatch(state: DemoState) -> DemoState:
    return {"dispatched": bool(state.get("approved"))}


def build_demo_graph() -> StateGraph:  # type: ignore[type-arg]
    graph: StateGraph = StateGraph(DemoState)  # type: ignore[type-arg]
    graph.add_node("prepare", _prepare)
    graph.add_node("human_review", _human_review)
    graph.add_node("dispatch", _dispatch)
    graph.add_edge(START, "prepare")
    graph.add_edge("prepare", "human_review")
    graph.add_edge("human_review", "dispatch")
    graph.add_edge("dispatch", END)
    return graph


DEMO_WORKER_YAML = """\
schema_version: "1.0"
worker_id: demo_approval
worker_version: "1.0.0"
domain: work_ops
graph_version: "1.0.0"
prompt_bundle_version: "1.0.0"
toolset_version: "1.0.0"
policy_version: "1.0.0"
memory_policy_version: "1.0.0"
default_model_profile: balanced
supported_channels: [web]
autonomy_level: A2
"""
