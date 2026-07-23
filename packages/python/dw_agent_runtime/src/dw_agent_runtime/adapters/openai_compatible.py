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
from dw_kernel.resilience import CircuitBreaker


@dataclass
class OpenAICompatibleAdapter:
    """Implements ``ModelProviderAdapter`` over HTTP.

    ``structured_mode``:
    - "json_schema": native structured output (OpenAI, vLLM >= 0.6, ...)
    - "json_object": JSON mode + schema embedded in the prompt (DeepSeek, older
      providers). Output is still validated against the schema by the gateway.
    """

    base_url: str
    api_key: str
    provider: str = "openai_compatible"
    structured_mode: str = "json_schema"
    breaker: CircuitBreaker | None = None  # trips on repeated provider failures

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
        if self.structured_mode == "json_object":
            schema_hint = (
                "\n\nTrả về DUY NHẤT một JSON object hợp lệ đúng schema sau, "
                "không kèm giải thích:\n" + json.dumps(json_schema, ensure_ascii=False)
            )
            messages = [
                {"role": "system", "content": prompt.system + schema_hint},
                {"role": "user", "content": prompt.user},
            ]
            response_format: dict[str, object] = {"type": "json_object"}
        else:
            messages = [
                {"role": "system", "content": prompt.system},
                {"role": "user", "content": prompt.user},
            ]
            response_format = {
                "type": "json_schema",
                "json_schema": {"name": "structured_output", "schema": json_schema},
            }
        body: dict[str, object] = {
            "model": route.model,
            "messages": messages,
            "response_format": response_format,
        }
        if max_output_tokens:
            body["max_tokens"] = max_output_tokens

        if self.breaker is not None:
            self.breaker.before_call()
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
            if self.breaker is not None:
                self.breaker.record_failure()
            raise InfrastructureError(
                "model provider timed out",
                details={"provider": self.provider, "model": route.model},
            ) from exc
        except httpx.HTTPError as exc:
            if self.breaker is not None:
                self.breaker.record_failure()
            raise InfrastructureError(
                "model provider request failed",
                details={"provider": self.provider, "error": type(exc).__name__},
            ) from exc
        if self.breaker is not None:
            self.breaker.record_success()

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
