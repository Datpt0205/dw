"""Telemetry port, OTel adapter and Langfuse OTLP configuration."""

from __future__ import annotations

import base64

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from dw_observability.langfuse import langfuse_otlp_config
from dw_observability.otel import OtelTelemetry
from dw_observability.telemetry import NullTelemetry, RecordingTelemetry, safe_attributes

pytestmark = pytest.mark.unit


def test_safe_attributes_redacts_and_coerces() -> None:
    cleaned = safe_attributes(
        {
            "dw.worker_id": "tender",
            "api_key": "sk-super-secret",
            "count": 3,
            "none_dropped": None,
            "uuid_like": {"nested": "x"},
        }
    )
    assert cleaned["api_key"] == "[REDACTED]"
    assert cleaned["dw.worker_id"] == "tender"
    assert cleaned["count"] == 3
    assert "none_dropped" not in cleaned
    assert isinstance(cleaned["uuid_like"], str)


def test_null_telemetry_is_silent() -> None:
    telemetry = NullTelemetry()
    with telemetry.span("dw.run.start", {"a": 1}):
        telemetry.add_metric("dw_run_total", 1, {"worker": "tender"})


def test_otel_telemetry_exports_spans_and_metrics() -> None:
    span_exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    metric_reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[metric_reader])

    telemetry = OtelTelemetry(
        tracer=tracer_provider.get_tracer("test"), meter=meter_provider.get_meter("test")
    )
    with telemetry.span("dw.run.start", {"dw.worker_id": "tender", "token": "secret!"}):
        pass
    telemetry.add_metric("dw_run_total", 1, {"worker": "tender", "status": "completed"})
    telemetry.add_metric("dw_run_total", 1, {"worker": "tender", "status": "completed"})

    spans = span_exporter.get_finished_spans()
    assert [s.name for s in spans] == ["dw.run.start"]
    assert spans[0].attributes is not None
    assert spans[0].attributes["dw.worker_id"] == "tender"
    assert spans[0].attributes["token"] == "[REDACTED]"

    metrics_data = metric_reader.get_metrics_data()
    assert metrics_data is not None
    points = [
        point
        for resource in metrics_data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
        for point in metric.data.data_points
    ]
    assert points and points[0].value == 2  # type: ignore[union-attr]


def test_otel_span_records_exception_status() -> None:
    span_exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    meter = MeterProvider(metric_readers=[InMemoryMetricReader()]).get_meter("test")
    telemetry = OtelTelemetry(tracer=provider.get_tracer("test"), meter=meter)

    with pytest.raises(ValueError):
        with telemetry.span("dw.run.start", {}):
            raise ValueError("boom")
    span = span_exporter.get_finished_spans()[0]
    assert not span.status.is_ok


def test_langfuse_config_builds_basic_auth_otlp_endpoint() -> None:
    endpoint, headers = langfuse_otlp_config("https://cloud.langfuse.com/", "pk-x", "sk-y")
    assert endpoint == "https://cloud.langfuse.com/api/public/otel/v1/traces"
    scheme, _, token = headers["Authorization"].partition(" ")
    assert scheme == "Basic"
    assert base64.b64decode(token).decode() == "pk-x:sk-y"


def test_langfuse_config_rejects_missing_scheme_or_keys() -> None:
    with pytest.raises(ValueError, match="scheme"):
        langfuse_otlp_config("cloud.langfuse.com", "pk", "sk")
    with pytest.raises(ValueError, match="keys"):
        langfuse_otlp_config("https://cloud.langfuse.com", "pk", "")


def test_recording_telemetry_captures_for_assertions() -> None:
    telemetry = RecordingTelemetry()
    with telemetry.span("dw.run.start", {"dw.worker_id": "work_ops"}):
        pass
    telemetry.add_metric("dw_run_total", 1, {"worker": "work_ops"})
    assert telemetry.spans == [("dw.run.start", {"dw.worker_id": "work_ops"})]
    assert telemetry.metrics == [("dw_run_total", 1, {"worker": "work_ops"})]
