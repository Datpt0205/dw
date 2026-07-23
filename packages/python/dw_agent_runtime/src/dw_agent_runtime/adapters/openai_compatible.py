"""OpenAI-compatible chat-completions adapter (real provider path, ADR-012).

Works with any endpoint speaking the /chat/completions dialect (OpenAI, Azure
OpenAI with base_url, vLLM, Ollama-openai, ...). Enabled via configuration;
the production profile refuses to run with the mock instead of this.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx

from dw_agent_runtime.model.gateway import ModelUsage
from dw_agent_runtime.model.profiles import ModelRoute
from dw_agent_runtime.model.prompts import RenderedPrompt
from dw_kernel.errors import InfrastructureError


@dataclass
class OpenAICompatibleAdapter:
    """Implements ``ModelProviderAdapter`` over HTTP."""

    base_url: str
    api_key: str
    provider: str = "openai_compatible"

    @property
    def provider_name(self) -> str:
        return self.provider

    async def complete_json(
        self,
        prompt: RenderedPrompt,
        json_schema: dict[str, object],
        route: ModelRoute,
        *,
        max_output_tokens: int | None,
    ) -> tuple[dict[str, object], ModelUsage]:
        body: dict[str, object] = {
            "model": route.model,
            "messages": [
                {"role": "system", "content": prompt.system},
                {"role": "user", "content": prompt.user},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "structured_output", "schema": json_schema},
            },
        }
        if max_output_tokens:
            body["max_tokens"] = max_output_tokens

        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=route.timeout_seconds,
            ) as client:
                response = await client.post("/chat/completions", json=body)
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as exc:
            raise InfrastructureError(
                "model provider timed out",
                details={"provider": self.provider, "model": route.model},
            ) from exc
        except httpx.HTTPError as exc:
            raise InfrastructureError(
                "model provider request failed",
                details={"provider": self.provider, "error": type(exc).__name__},
            ) from exc

        try:
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            if not isinstance(parsed, dict):
                raise ValueError("model returned non-object JSON")
            usage_data = data.get("usage", {})
        except (KeyError, IndexError, ValueError, json.JSONDecodeError) as exc:
            raise InfrastructureError(
                "model provider returned an unparseable response",
                details={"provider": self.provider},
            ) from exc

        usage = ModelUsage(
            provider=self.provider,
            model=route.model,
            input_tokens=int(usage_data.get("prompt_tokens", 0)),
            output_tokens=int(usage_data.get("completion_tokens", 0)),
        )
        return parsed, usage
