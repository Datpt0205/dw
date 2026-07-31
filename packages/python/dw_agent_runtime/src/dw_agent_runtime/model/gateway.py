"""Routing model gateway: the single entry point for LLM calls.

Output is ALWAYS validated into the caller's Pydantic schema; provider adapters
are selected per profile (Strategy). Usage/cost is recorded per call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from pydantic import ValidationError

from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.model.profiles import ModelProfileRegistry, ModelRoute
from dw_agent_runtime.model.prompts import PromptRegistry, RenderedPrompt
from dw_agent_runtime.ports import ModelRequest, OutputT
from dw_kernel.errors import DomainError, NotFoundError


@dataclass(frozen=True)
class ModelUsage:
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float = 0.0


class ModelProviderAdapter(Protocol):
    """One provider integration (mock, OpenAI-compatible, vLLM, ...)."""

    @property
    def provider_name(self) -> str: ...

    async def complete_json(
        self,
        prompt: RenderedPrompt,
        json_schema: dict[str, object],
        route: ModelRoute,
        *,
        max_output_tokens: int | None,
    ) -> tuple[dict[str, object], ModelUsage, str | None]:
        """Returns (parsed_json, usage, visible_reasoning_or_None)."""
        ...


class UsageRecorderPort(Protocol):
    def record(self, run_context: RunContext, request: ModelRequest, usage: ModelUsage) -> None: ...


@dataclass
class InMemoryUsageRecorder:
    """Default recorder; OTel/Langfuse exporters replace it in phase 5."""

    records: list[tuple[str, ModelUsage]] = field(default_factory=list)

    def record(self, run_context: RunContext, request: ModelRequest, usage: ModelUsage) -> None:
        self.records.append((str(run_context.run_id), usage))


@dataclass
class RoutingModelGateway:
    """Implements the ``ModelGateway`` port with per-profile routing."""

    profiles: ModelProfileRegistry
    prompts: PromptRegistry
    adapters: dict[str, ModelProviderAdapter]
    usage_recorder: UsageRecorderPort

    def _route(self, request: ModelRequest) -> ModelRoute:
        profile = self.profiles.resolve(request.model_profile)
        if request.route_kind == "deep_reasoning":
            # Visible-thinking route is optional; degrade to reasoning route.
            return profile.deep_reasoning or profile.reasoning
        if request.route_kind == "reasoning" or (
            request.route_kind == "auto" and request.task == "reasoning"
        ):
            return profile.reasoning
        return profile.structured_extraction

    async def generate_structured(
        self,
        request: ModelRequest,
        output_type: type[OutputT],
        *,
        run_context: RunContext,
    ) -> OutputT:
        output, _reasoning = await self.generate_structured_traced(
            request, output_type, run_context=run_context
        )
        return output

    async def generate_structured_traced(
        self,
        request: ModelRequest,
        output_type: type[OutputT],
        *,
        run_context: RunContext,
    ) -> tuple[OutputT, str]:
        route = self._route(request)
        adapter = self.adapters.get(route.provider)
        if adapter is None:
            raise NotFoundError(
                "model provider not configured",
                details={"provider": route.provider, "profile": request.model_profile},
            )
        prompt = self.prompts.render(
            request.prompt_id, request.prompt_version, dict(request.variables)
        )
        raw, usage, reasoning = await adapter.complete_json(
            prompt,
            output_type.model_json_schema(),
            route,
            max_output_tokens=request.max_output_tokens,
        )
        self.usage_recorder.record(run_context, request, usage)
        try:
            return output_type.model_validate(raw), reasoning or ""
        except ValidationError as exc:
            raise DomainError(
                "model output failed schema validation",
                details={
                    "prompt_id": request.prompt_id,
                    "output_type": output_type.__name__,
                    "errors": str(exc.error_count()),
                },
            ) from exc
