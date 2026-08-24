"""Deep Agents core plugged into the existing LangGraph runner (lab sandbox).

``create_deep_agent`` returns an already-compiled graph, while
``LangGraphWorkflowRunner._graph`` expects a factory whose product it compiles
itself::

    factory().compile(checkpointer=self.checkpoint_saver)

``DeepAgentGraphSpec`` is the adapter between those two shapes: it looks like an
uncompiled graph to the runner and defers to ``create_deep_agent`` on compile,
handing the tenant-aware ``SqlAlchemyCheckpointSaver`` straight through. Nothing
else in the runtime changes — durable checkpoints, the interrupt→ApprovalRequest
mapping, the run store, audit and telemetry all keep working as they are.

Deep Agents takes a LangChain ``BaseChatModel``, which the platform's own
``ModelGateway`` port is not; ``chat_model_from_route`` builds one from the very
same ``configs/models/*.yaml`` route so a deepagents run and a gateway run hit
the same model. That bypass is deliberate and lab-only — promoting it to ``dw``
needs an ADR (CLAUDE.md §"Do not silently change the architecture").
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from deepagents import create_deep_agent
from langchain_core.language_models import BaseChatModel

from dw_agent_runtime.model.profiles import ModelRoute


def chat_model_from_route(
    route: ModelRoute,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
) -> BaseChatModel:
    """A LangChain chat model on the same endpoint/model as a gateway route.

    Falls back to OPENAI_API_KEY / OPENAI_BASE_URL, the variables the compose
    stack and ``scripts/dev.sh`` already export.
    """
    from langchain_openai import ChatOpenAI

    kwargs: dict[str, Any] = {
        "model": route.model,
        "timeout": route.timeout_seconds,
        "api_key": api_key or os.environ.get("OPENAI_API_KEY") or "unset",
    }
    resolved_base = base_url or os.environ.get("OPENAI_BASE_URL")
    if resolved_base:
        kwargs["base_url"] = resolved_base
    if route.reasoning_effort is not None:
        kwargs["reasoning_effort"] = route.reasoning_effort
    return ChatOpenAI(**kwargs)


@dataclass
class DeepAgentGraphSpec:
    """Registry-shaped wrapper: ``.compile(checkpointer=...)`` -> deep agent.

    Register it like any other graph::

        graph_registry.register(
            "preparation", "2.0.0-deepagents",
            lambda: DeepAgentGraphSpec(model=..., system_prompt=..., tools=[...]),
        )
    """

    model: BaseChatModel
    system_prompt: str
    tools: Sequence[Any] = field(default_factory=tuple)
    subagents: Sequence[Any] = field(default_factory=tuple)
    # Tool name -> True | InterruptOnConfig. Each interrupt surfaces in
    # state["__interrupt__"], which the runner already turns into an
    # ApprovalRequest and a WAITING_APPROVAL run.
    interrupt_on: dict[str, Any] | None = None
    middleware: Sequence[Any] = field(default_factory=tuple)
    backend: Any | None = None
    state_schema: Any | None = None
    name: str | None = None

    def compile(self, *, checkpointer: Any) -> Any:
        return create_deep_agent(
            model=self.model,
            tools=list(self.tools),
            system_prompt=self.system_prompt,
            subagents=list(self.subagents) or None,
            interrupt_on=self.interrupt_on,
            middleware=tuple(self.middleware),
            backend=self.backend,
            state_schema=self.state_schema,
            name=self.name,
            checkpointer=checkpointer,
        )
