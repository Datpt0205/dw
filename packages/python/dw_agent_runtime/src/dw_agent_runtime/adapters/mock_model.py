"""Deterministic mock model adapter (ADR-012) — default for local/test.

Responses come from registered builders or JSON fixtures keyed by prompt id +
version. Output is real data that must satisfy the caller's schema; nothing
here raises NotImplementedError.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from dw_agent_runtime.model.gateway import ModelUsage
from dw_agent_runtime.model.profiles import ModelRoute
from dw_agent_runtime.model.prompts import RenderedPrompt
from dw_kernel.errors import NotFoundError

ResponseBuilder = Callable[[RenderedPrompt], dict[str, object]]

PROVIDER_NAME = "mock"


@dataclass
class MockModelAdapter:
    """Implements ``ModelProviderAdapter`` deterministically."""

    fixtures_dir: Path | None = None
    _builders: dict[tuple[str, str], ResponseBuilder] = field(default_factory=dict)
    calls: list[RenderedPrompt] = field(default_factory=list)

    @property
    def provider_name(self) -> str:
        return PROVIDER_NAME

    def register_builder(self, prompt_id: str, version: str, builder: ResponseBuilder) -> None:
        self._builders[(prompt_id, version)] = builder

    def _fixture_response(self, prompt: RenderedPrompt) -> dict[str, object] | None:
        if self.fixtures_dir is None:
            return None
        path = self.fixtures_dir / f"{prompt.prompt_id}@{prompt.version}.json"
        if not path.exists():
            return None
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise NotFoundError(
                "mock fixture must contain a JSON object",
                details={"fixture": path.name},
            )
        return loaded

    async def complete_json(
        self,
        prompt: RenderedPrompt,
        json_schema: dict[str, object],
        route: ModelRoute,
        *,
        max_output_tokens: int | None,
    ) -> tuple[dict[str, object], ModelUsage, str | None]:
        self.calls.append(prompt)

        builder = self._builders.get((prompt.prompt_id, prompt.version))
        if builder is not None:
            response = builder(prompt)
        else:
            fixture = self._fixture_response(prompt)
            if fixture is None:
                raise NotFoundError(
                    "no mock response registered for prompt",
                    details={"prompt_id": prompt.prompt_id, "version": prompt.version},
                )
            response = fixture

        usage = ModelUsage(
            provider=PROVIDER_NAME,
            model=route.model,
            input_tokens=max(1, len(prompt.user) // 4),
            output_tokens=max(1, len(json.dumps(response)) // 4),
            cost_usd=0.0,
        )
        return response, usage, None
