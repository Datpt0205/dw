"""Unit tests for the OpenAI Responses adapter internals (ADR-020)."""

from __future__ import annotations

import pytest

from dw_agent_runtime.adapters.openai_responses import (
    _build_request_body,
    _parse_responses_payload,
    _to_strict_schema,
)
from dw_agent_runtime.model.profiles import ModelRoute
from dw_agent_runtime.model.prompts import RenderedPrompt

pytestmark = pytest.mark.unit


def _payload(output: list[dict[str, object]]) -> dict[str, object]:
    return {"output": output, "usage": {"input_tokens": 10, "output_tokens": 5}}


def test_parses_json_and_reasoning_summary() -> None:
    data = _payload(
        [
            {
                "type": "reasoning",
                "summary": [
                    {"type": "summary_text", "text": "Người dùng nêu ngân sách 7,5 tỷ."},
                    {"type": "summary_text", "text": "Trên ngưỡng 5 tỷ → đấu thầu."},
                ],
            },
            {
                "type": "message",
                "content": [{"type": "output_text", "text": '{"intent": "provide_info"}'}],
            },
        ]
    )
    parsed, reasoning = _parse_responses_payload(data)
    assert parsed == {"intent": "provide_info"}
    assert reasoning is not None
    assert "7,5 tỷ" in reasoning and "đấu thầu" in reasoning
    assert reasoning.count("\n") == 1  # two summary parts joined line-by-line


def test_reasoning_absent_is_none_not_error() -> None:
    data = _payload(
        [{"type": "message", "content": [{"type": "output_text", "text": '{"ok": true}'}]}]
    )
    parsed, reasoning = _parse_responses_payload(data)
    assert parsed == {"ok": True}
    assert reasoning is None


def test_output_text_split_across_parts_is_joined() -> None:
    data = _payload(
        [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": '{"a": '},
                    {"type": "output_text", "text": "1}"},
                ],
            }
        ]
    )
    parsed, _ = _parse_responses_payload(data)
    assert parsed == {"a": 1}


def test_refusal_raises_value_error() -> None:
    data = _payload(
        [{"type": "message", "content": [{"type": "refusal", "refusal": "cannot comply"}]}]
    )
    with pytest.raises(ValueError, match="refused"):
        _parse_responses_payload(data)


def test_missing_output_text_raises() -> None:
    with pytest.raises(ValueError, match="no output_text"):
        _parse_responses_payload(_payload([{"type": "reasoning", "summary": []}]))


def _prompt() -> RenderedPrompt:
    return RenderedPrompt(
        prompt_id="demo.p", version="1.0.0", system="sys", user="usr", checksum="x"
    )


def test_build_body_includes_effort_and_summary() -> None:
    route = ModelRoute(
        provider="openai_responses", model="gpt-5", timeout_seconds=60, reasoning_effort="low"
    )
    body = _build_request_body(
        _prompt(),
        {"type": "object"},
        route,
        reasoning_summary="auto",
        strict_schema=False,
        max_output_tokens=None,
    )
    assert body["reasoning"] == {"summary": "auto", "effort": "low"}
    assert body["model"] == "gpt-5"
    fmt = body["text"]["format"]  # type: ignore[index]
    assert fmt["type"] == "json_schema" and "strict" not in fmt


def test_build_body_without_effort_omits_it() -> None:
    route = ModelRoute(provider="openai_responses", model="gpt-5", timeout_seconds=60)
    body = _build_request_body(
        _prompt(),
        {"type": "object"},
        route,
        reasoning_summary="auto",
        strict_schema=False,
        max_output_tokens=500,
    )
    assert body["reasoning"] == {"summary": "auto"}
    assert body["max_output_tokens"] == 500


def test_strict_schema_transform_closes_objects_and_strips_constraints() -> None:
    schema = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "pattern": r"^REQ-\d{2}$", "minLength": 1},
            "nested": {
                "type": "object",
                "properties": {"n": {"type": "integer", "minimum": 0, "default": 3}},
            },
            "items": {"type": "array", "items": {"type": "string", "maxLength": 5}},
        },
        "required": ["code"],
    }
    strict = _to_strict_schema(schema)
    assert strict["additionalProperties"] is False
    assert sorted(strict["required"]) == ["code", "items", "nested"]
    assert "pattern" not in strict["properties"]["code"]
    assert "minLength" not in strict["properties"]["code"]
    nested = strict["properties"]["nested"]
    assert nested["additionalProperties"] is False and nested["required"] == ["n"]
    assert "minimum" not in nested["properties"]["n"] and "default" not in nested["properties"]["n"]
    assert "maxLength" not in strict["properties"]["items"]["items"]


def test_strict_flag_transforms_body_schema() -> None:
    route = ModelRoute(provider="openai_responses", model="gpt-5", timeout_seconds=60)
    body = _build_request_body(
        _prompt(),
        {"type": "object", "properties": {"a": {"type": "string", "pattern": "x"}}},
        route,
        reasoning_summary="",
        strict_schema=True,
        max_output_tokens=None,
    )
    fmt = body["text"]["format"]  # type: ignore[index]
    assert fmt["strict"] is True
    assert fmt["schema"]["additionalProperties"] is False
    assert "pattern" not in fmt["schema"]["properties"]["a"]
    assert "reasoning" not in body  # summary "" disables the block entirely


def test_strict_schema_strips_ref_siblings() -> None:
    # Pydantic emits {"$ref": ..., "description": ...} for annotated nested
    # models; strict mode rejects ANY sibling keyword next to $ref.
    schema = {
        "type": "object",
        "properties": {
            "slots": {"$ref": "#/$defs/IntakeSlots", "description": "chỉ điền thứ tin nhắn nói"}
        },
        "$defs": {"IntakeSlots": {"type": "object", "properties": {"q": {"type": "integer"}}}},
    }
    strict = _to_strict_schema(schema)
    assert strict["properties"]["slots"] == {"$ref": "#/$defs/IntakeSlots"}
    assert strict["$defs"]["IntakeSlots"]["additionalProperties"] is False
