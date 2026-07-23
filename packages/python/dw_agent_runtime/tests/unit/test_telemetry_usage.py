"""TelemetryUsageRecorder emits §21.3 token metrics with safe labels only."""

from __future__ import annotations

import uuid

import pytest

from dw_agent_runtime.adapters.telemetry_usage import TelemetryUsageRecorder
from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.model.gateway import ModelUsage
from dw_agent_runtime.ports import ModelRequest
from dw_observability.metrics import DW_MODEL_TOKENS_TOTAL
from dw_observability.telemetry import RecordingTelemetry

pytestmark = pytest.mark.unit


def _run_context() -> RunContext:
    return RunContext(
        run_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        worker_id="tender",
        worker_version="1.0.0",
        channel="web",
        plan_id="starter",
        roles=frozenset({"member"}),
        scopes=frozenset(),
        trace_id="test-trace",
    )


def test_records_token_metrics_and_model_span() -> None:
    telemetry = RecordingTelemetry()
    recorder = TelemetryUsageRecorder(telemetry)
    request = ModelRequest(
        prompt_id="tender.extract_requirements",
        prompt_version="1.0.0",
        model_profile="balanced",
        task="structured_extraction",
        variables={"rfq": "salary data and other secrets"},
    )
    usage = ModelUsage(provider="mock", model="mock-structured", input_tokens=120, output_tokens=45)

    recorder.record(_run_context(), request, usage)

    directions = {
        (m[2]["direction"], m[1]) for m in telemetry.metrics if m[0] == DW_MODEL_TOKENS_TOTAL
    }
    assert directions == {("input", 120), ("output", 45)}
    (span_name, attributes) = telemetry.spans[0]
    assert span_name == "dw.model.call"
    assert attributes["dw.prompt_id"] == "tender.extract_requirements"
    # prompt content must never appear in telemetry attributes
    assert all("salary" not in str(v) for v in attributes.values())
