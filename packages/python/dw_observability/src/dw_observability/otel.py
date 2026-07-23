"""OpenTelemetry implementation of ``TelemetryPort`` (blueprint §21).

``configure_tracing`` builds a real SDK pipeline when an OTLP endpoint is
configured (plain collector or Langfuse — see ``dw_observability.langfuse``).
Without an endpoint the API-level no-op tracer applies, so instrumented code
never pays for unconfigured telemetry.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field

from opentelemetry import metrics, trace
from opentelemetry.metrics import Counter, Meter
from opentelemetry.trace import Status, StatusCode, Tracer

from dw_observability.telemetry import safe_attributes


def configure_tracing(
    service_name: str,
    *,
    otlp_endpoint: str | None = None,
    otlp_headers: Mapping[str, str] | None = None,
) -> tuple[Tracer, Meter]:
    """Install a tracer/meter provider; export via OTLP when an endpoint is set."""
    if otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(
                    endpoint=otlp_endpoint,
                    headers=dict(otlp_headers) if otlp_headers else None,
                )
            )
        )
        trace.set_tracer_provider(provider)
    return trace.get_tracer(service_name), metrics.get_meter(service_name)


@dataclass
class OtelTelemetry:
    """``TelemetryPort`` on an OpenTelemetry tracer + meter."""

    tracer: Tracer
    meter: Meter
    _counters: dict[str, Counter] = field(default_factory=dict)

    @contextmanager
    def _span(self, name: str, attributes: Mapping[str, object]) -> Iterator[None]:
        with self.tracer.start_as_current_span(name) as span:
            for key, value in safe_attributes(attributes).items():
                span.set_attribute(key, value)
            try:
                yield
            except Exception as exc:
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                span.record_exception(exc)
                raise

    def span(self, name: str, attributes: Mapping[str, object]) -> AbstractContextManager[None]:
        return self._span(name, attributes)

    def add_metric(self, name: str, value: int | float, attributes: Mapping[str, object]) -> None:
        counter = self._counters.get(name)
        if counter is None:
            counter = self.meter.create_counter(name)
            self._counters[name] = counter
        counter.add(value, safe_attributes(attributes))
