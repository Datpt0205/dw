"""Runtime ports: workflow runner and model gateway.

LangGraph and provider SDK adapters implement these in phase 2; workflow nodes
and application handlers depend only on the protocols.
"""

from __future__ import annotations

from typing import Protocol, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from dw_agent_runtime.contracts import RunContext

OutputT = TypeVar("OutputT", bound=BaseModel)


class ModelRequest(BaseModel):
    """Provider-neutral request for a structured model call."""

    model_config = ConfigDict(frozen=True)

    task: str
    prompt_id: str
    prompt_version: str
    variables: dict[str, str] = {}
    model_profile: str = "balanced"
    max_output_tokens: int | None = None


class ModelGateway(Protocol):
    """Single entry point for LLM calls; output is always schema-validated."""

    async def generate_structured(
        self,
        request: ModelRequest,
        output_type: type[OutputT],
        *,
        run_context: RunContext,
    ) -> OutputT: ...


class WorkflowRunnerPort(Protocol):
    """Starts and resumes durable, checkpointed workflow runs."""

    async def start(
        self,
        *,
        run_context: RunContext,
        input_payload: dict[str, object],
    ) -> UUID: ...

    async def resume(
        self,
        *,
        run_context: RunContext,
        run_id: UUID,
        resume_payload: dict[str, object],
    ) -> None: ...
