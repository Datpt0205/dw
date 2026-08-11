"""OpenAI Responses API adapter: structured output + native reasoning summary.

GPT-5-era models reason internally; ``/v1/responses`` can return an official
summary of that reasoning (``reasoning: {summary: "auto"}``) alongside the
answer. This adapter surfaces it as the visible-reasoning tuple element so
channels can show real model thinking — chat/completions never exposes it
(ADR-020). Structured output uses the native ``text.format`` json_schema.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from dw_agent_runtime.adapters.openai_compatible import _extract_json_object
from dw_agent_runtime.model.gateway import ModelUsage
from dw_agent_runtime.model.profiles import ModelRoute
from dw_agent_runtime.model.prompts import RenderedPrompt
from dw_kernel.errors import InfrastructureError
from dw_kernel.resilience import CircuitBreaker

logger = logging.getLogger("dw_agent_runtime.openai_responses")


@dataclass
class OpenAIResponsesAdapter:
    """Implements ``ModelProviderAdapter`` over the OpenAI ``/responses`` endpoint.

    Only meaningful against api.openai.com (or a proxy speaking the Responses
    dialect); generic OpenAI-compatible providers stay on the chat/completions
    adapter. ``reasoning_summary``: "auto" | "detailed" | "" (omit request).
    """

    base_url: str
    api_key: str
    provider: str = "openai_responses"
    reasoning_summary: str = "auto"
    # The Responses API REQUIRES strict-style schemas (additionalProperties
    # false, required-all) — verified live 2026-08: non-strict is rejected
    # with invalid_json_schema. Default ON; the flag remains only as an
    # escape hatch for future gateways that deviate.
    strict_schema: bool = True
    breaker: CircuitBreaker | None = None

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
    ) -> tuple[dict[str, object], ModelUsage, str | None]:
        body = _build_request_body(
            prompt,
            json_schema,
            route,
            reasoning_summary=self.reasoning_summary,
            strict_schema=self.strict_schema,
            max_output_tokens=max_output_tokens,
        )

        if self.breaker is not None:
            self.breaker.before_call()
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=route.timeout_seconds,
            ) as client:
                response = await client.post("/responses", json=body)
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as exc:
            if self.breaker is not None:
                self.breaker.record_failure()
            raise InfrastructureError(
                "model provider timed out",
                details={"provider": self.provider, "model": route.model},
            ) from exc
        except httpx.HTTPStatusError as exc:
            if self.breaker is not None:
                self.breaker.record_failure()
            # Surface the provider's own error message — a bare 400 is
            # undebuggable (schema? content filter? model access?).
            body_text = exc.response.text[:500]
            logger.warning(
                "openai_responses %s %s: %s", exc.response.status_code, route.model, body_text
            )
            if exc.response.status_code == 400:
                # Schema rejections have been non-reproducible offline — dump
                # exactly what left this process so gateway-side rewrites show.
                logger.warning(
                    "sent text.format: %s",
                    json.dumps(body.get("text"), ensure_ascii=False)[:3000],
                )
            raise InfrastructureError(
                "model provider request failed",
                details={
                    "provider": self.provider,
                    "status": str(exc.response.status_code),
                    "body": body_text,
                },
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
            parsed, reasoning = _parse_responses_payload(data)
            usage_data = data.get("usage", {})
        except (KeyError, IndexError, ValueError, json.JSONDecodeError) as exc:
            raise InfrastructureError(
                "model provider returned an unparseable response",
                details={"provider": self.provider},
            ) from exc

        usage = ModelUsage(
            provider=self.provider,
            model=route.model,
            input_tokens=int(usage_data.get("input_tokens", 0)),
            output_tokens=int(usage_data.get("output_tokens", 0)),
        )
        return parsed, usage, reasoning


def _build_request_body(
    prompt: RenderedPrompt,
    json_schema: dict[str, object],
    route: ModelRoute,
    *,
    reasoning_summary: str,
    strict_schema: bool,
    max_output_tokens: int | None,
) -> dict[str, object]:
    text_format: dict[str, object] = {
        "type": "json_schema",
        "name": "structured_output",
        "schema": _to_strict_schema(json_schema) if strict_schema else json_schema,
    }
    if strict_schema:
        text_format["strict"] = True
    body: dict[str, object] = {
        "model": route.model,
        "instructions": prompt.system,
        "input": [{"role": "user", "content": prompt.user}],
        "text": {"format": text_format},
    }
    # ``reasoning`` is only valid for reasoning models, and a route declares it
    # is one by carrying reasoning_effort. Sending the block to gpt-4.1/4o gets
    # the whole request rejected, so a route without an effort gets none.
    if route.reasoning_effort is not None:
        reasoning: dict[str, object] = {"effort": route.reasoning_effort}
        if reasoning_summary:
            reasoning["summary"] = reasoning_summary
        body["reasoning"] = reasoning
    if max_output_tokens:
        body["max_output_tokens"] = max_output_tokens
    return body


# JSON Schema keywords OpenAI strict mode rejects — validation still happens
# locally (Pydantic re-checks the full schema on every response).
_STRICT_UNSUPPORTED = frozenset(
    {
        "pattern",
        "format",
        "default",
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minItems",
        "maxItems",
        "uniqueItems",
    }
)


def _to_strict_schema(schema: object) -> Any:
    """Transform a Pydantic-generated schema into OpenAI-strict form.

    Strict mode demands: every object closes with additionalProperties=false
    and lists ALL properties as required; unsupported constraint keywords are
    stripped (the grammar guarantees structure — Pydantic still enforces the
    stripped constraints when validating the response).
    """
    if isinstance(schema, list):
        return [_to_strict_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    result: dict[str, object] = {
        key: _to_strict_schema(value)
        for key, value in schema.items()
        if key not in _STRICT_UNSUPPORTED
    }
    # Strict mode forbids ANY sibling keyword next to $ref (Pydantic emits
    # {"$ref": ..., "description": ...} for annotated nested models).
    if "$ref" in result:
        return {"$ref": result["$ref"]}
    properties = result.get("properties")
    if isinstance(properties, dict):
        result["additionalProperties"] = False
        result["required"] = list(properties.keys())
    return result


def _parse_responses_payload(data: Any) -> tuple[dict[str, object], str | None]:
    """Extract (json_object, reasoning_summary_or_None) from a Responses payload.

    The ``output`` array interleaves item types: ``reasoning`` items carry
    ``summary`` parts; ``message`` items carry ``output_text``/``refusal``
    content parts. Reasoning summaries may be absent (fast answers, or the
    feature unavailable on the account) — that is not an error.
    """
    summaries: list[str] = []
    text_parts: list[str] = []
    for item in data.get("output") or []:
        item_type = item.get("type")
        if item_type == "reasoning":
            for part in item.get("summary") or []:
                if part.get("type") == "summary_text" and part.get("text"):
                    summaries.append(str(part["text"]))
        elif item_type == "message":
            for part in item.get("content") or []:
                part_type = part.get("type")
                if part_type == "output_text":
                    text_parts.append(str(part.get("text") or ""))
                elif part_type == "refusal":
                    raise ValueError(f"model refused: {part.get('refusal')}")
    if not text_parts:
        raise ValueError("model returned no output_text")
    parsed = _extract_json_object("".join(text_parts))
    reasoning = "\n".join(s.strip() for s in summaries if s.strip())
    return parsed, reasoning or None
