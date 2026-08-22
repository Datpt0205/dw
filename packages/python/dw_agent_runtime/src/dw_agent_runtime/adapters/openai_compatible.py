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
    ) -> tuple[dict[str, object], ModelUsage, str | None]:
        # Reasoning models (deepseek-reasoner, *-r1) emit visible thinking in
        # ``reasoning_content`` and do not support response_format — the schema
        # goes into the prompt and the JSON is extracted robustly instead.
        is_reasoner = "reasoner" in route.model or route.model.endswith("-r1")
        if self.structured_mode == "json_object" or is_reasoner:
            schema_hint = (
                "\n\nTrả về DUY NHẤT một JSON object theo đúng khuôn dưới đây. "
                "Thay mỗi <...> bằng giá trị thật; giữ nguyên tên field; không "
                "kèm giải thích:\n"
                + json.dumps(_schema_as_instruction(json_schema), ensure_ascii=False)
            )
            messages = [
                {"role": "system", "content": prompt.system + schema_hint},
                {"role": "user", "content": prompt.user},
            ]
            response_format: dict[str, object] | None = (
                None if is_reasoner else {"type": "json_object"}
            )
        else:
            messages = [
                {"role": "system", "content": prompt.system},
                {"role": "user", "content": prompt.user},
            ]
            response_format = {
                "type": "json_schema",
                "json_schema": {"name": "structured_output", "schema": json_schema},
            }
        body: dict[str, object] = {"model": route.model, "messages": messages}
        if response_format is not None:
            body["response_format"] = response_format
        if max_output_tokens:
            # OpenAI reasoning models (gpt-5*, o-series) reject `max_tokens`;
            # generic OpenAI-compatible providers (vLLM, DeepSeek) still use it.
            reasoning_family = route.model.startswith(("gpt-5", "o1", "o3", "o4"))
            body["max_completion_tokens" if reasoning_family else "max_tokens"] = max_output_tokens

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
            message = data["choices"][0]["message"]
            parsed = _extract_json_object(str(message.get("content") or ""))
            if response_format is None or response_format.get("type") != "json_schema":
                # Without a decoding constraint a model says "not applicable"
                # by writing null, including into fields typed as plain
                # strings. Absent is what it means, and absent is what the
                # schema's own defaults are for — so the nulls come out and
                # Pydantic fills the blanks it was always going to fill.
                parsed = _drop_nulls(parsed)
            usage_data = data.get("usage", {})
        except (KeyError, IndexError, ValueError, json.JSONDecodeError) as exc:
            raise InfrastructureError(
                "model provider returned an unparseable response",
                details={"provider": self.provider},
            ) from exc

        reasoning = message.get("reasoning_content")
        usage = ModelUsage(
            provider=self.provider,
            model=route.model,
            input_tokens=int(usage_data.get("prompt_tokens", 0)),
            output_tokens=int(usage_data.get("completion_tokens", 0)),
        )
        return parsed, usage, str(reasoning) if reasoning else None


def _drop_nulls(value: dict[str, object]) -> dict[str, object]:
    """Remove nulls, at every depth, leaving the defaults to apply."""

    def prune(node: object) -> object:
        if isinstance(node, dict):
            return {k: prune(v) for k, v in node.items() if v is not None}
        if isinstance(node, list):
            return [prune(item) for item in node if item is not None]
        return node

    pruned = prune(value)
    return pruned if isinstance(pruned, dict) else value


def _schema_as_instruction(schema: object) -> object:
    """A skeleton of the ANSWER, not the schema that describes it.

    Under ``json_schema`` the schema never reaches the model as text — the
    provider turns it into a decoding constraint. Under ``json_object`` it is
    pasted into the prompt, and asking for "a JSON object matching this schema"
    while showing a JSON object gets the schema echoed straight back.

    That is what broke the approval classifier. The model returned
    ``{"description": ..., "properties": {"decision": {"enum": [...]}}, ...}``
    — valid JSON, parsed cleanly, and validated cleanly too, because every real
    field was absent and Pydantic filled its defaults. So an explicit "duyệt
    cp2 hồ sơ do Lê Thu Hà đề nghị" arrived as ``decision="none"``: not a
    refusal the model made, a refusal the schema's own defaults invented. No
    exception, no retry, nothing to see in a log.

    A skeleton removes the ambiguity: there is one object in the instruction
    and it is shaped like the answer, with placeholders where values go.
    ``default`` is dropped on the way — it is what the APPLICATION uses when a
    field is missing, and showing it invites the model to pick it.
    """
    if not isinstance(schema, dict):
        return schema
    defs = schema.get("$defs")
    return _placeholder(schema, defs if isinstance(defs, dict) else {})


def _placeholder(spec: object, defs: dict[str, object], depth: int = 0) -> object:
    """One field's slot, described by what may go in it.

    Nested models arrive as ``$ref`` into ``$defs``, and optional ones as an
    ``anyOf`` of the model and ``null``. Both have to be followed: rendering a
    nested object as a string slot is an instruction to return a string there,
    and the model obliges — which is how ``slots``, ``addendum`` and
    ``submission`` came back as prose and failed validation.
    """
    if not isinstance(spec, dict) or depth > 6:
        return "<giá trị>"

    ref = spec.get("$ref")
    if isinstance(ref, str):
        target = defs.get(ref.rsplit("/", 1)[-1])
        merged = (
            {**target, **{k: v for k, v in spec.items() if k != "$ref"}}
            if (isinstance(target, dict))
            else spec
        )
        return _placeholder(merged, defs, depth + 1) if isinstance(target, dict) else "<giá trị>"

    branches = spec.get("anyOf") or spec.get("oneOf")
    if isinstance(branches, list):
        concrete = [b for b in branches if not (isinstance(b, dict) and b.get("type") == "null")]
        nullable = len(concrete) < len(branches)
        if concrete:
            inner = _placeholder({**concrete[0], **_carry(spec)}, defs, depth + 1)
            if nullable and isinstance(inner, str) and inner.endswith(">"):
                return inner[:-1] + ", hoặc null>"
            return inner
        return "<null>"

    if isinstance(spec.get("enum"), list):
        return "<" + "|".join(str(v) for v in spec["enum"]) + ">"

    nested = spec.get("properties")
    if isinstance(nested, dict):
        return {name: _placeholder(inner, defs, depth + 1) for name, inner in nested.items()}

    kind = spec.get("type")
    if kind == "array":
        return [_placeholder(spec.get("items"), defs, depth + 1)]
    if kind == "boolean":
        return "<true|false>"
    hint = str(spec.get("description") or "")
    if kind in {"integer", "number"}:
        return f"<số — {hint}>" if hint else "<số>"
    return f"<{hint}>" if hint else f"<{kind or 'giá trị'}>"


def _carry(spec: dict[str, object]) -> dict[str, object]:
    """A description written on the field, not on the branch, still applies."""
    return {"description": spec["description"]} if "description" in spec else {}


def _extract_json_object(content: str) -> dict[str, object]:
    """Parse a JSON object from model text, tolerating code fences/preambles.

    Strict path first; reasoning models sometimes wrap the object in ```json
    fences or prepend prose, so fall back to the outermost {...} slice.
    """
    text = content.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("model returned no JSON object") from None
        parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("model returned non-object JSON")
    return parsed
