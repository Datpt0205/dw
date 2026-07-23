"""Telemetry port: how runtime code emits spans/metrics without knowing OTel.

The runtime depends on this small protocol only; the OTel implementation lives
in ``dw_observability.otel`` and is wired by the composition root. Attributes
are redacted before leaving the process and must stay low-cardinality.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager, nullcontext
from typing import Protocol

from dw_observability.redaction import redact_mapping

AttributeValue = str | int | float | bool


def safe_attributes(attributes: Mapping[str, object]) -> dict[str, AttributeValue]:
    """Redact secrets, drop None and coerce everything else to OTel-safe types."""
    cleaned: dict[str, AttributeValue] = {}
    for key, value in redact_mapping(attributes).items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            cleaned[key] = value
        else:
            cleaned[key] = str(value)
    return cleaned


class TelemetryPort(Protocol):
    """Constructor-injected sink for spans and counters (never a global)."""

    def span(self, name: str, attributes: Mapping[str, object]) -> AbstractContextManager[None]: ...

    def add_metric(
        self, name: str, value: int | float, attributes: Mapping[str, object]
    ) -> None: ...


class NullTelemetry:
    """Default: no telemetry configured — everything is a no-op."""

    def span(self, name: str, attributes: Mapping[str, object]) -> AbstractContextManager[None]:
        return nullcontext()

    def add_metric(self, name: str, value: int | float, attributes: Mapping[str, object]) -> None:
        return None


class RecordingTelemetry:
    """In-memory sink for tests: captures what production code would emit."""

    def __init__(self) -> None:
        self.spans: list[tuple[str, dict[str, AttributeValue]]] = []
        self.metrics: list[tuple[str, int | float, dict[str, AttributeValue]]] = []

    @contextmanager
    def _record(self, name: str, attributes: Mapping[str, object]) -> Iterator[None]:
        self.spans.append((name, safe_attributes(attributes)))
        yield

    def span(self, name: str, attributes: Mapping[str, object]) -> AbstractContextManager[None]:
        return self._record(name, attributes)

    def add_metric(self, name: str, value: int | float, attributes: Mapping[str, object]) -> None:
        self.metrics.append((name, value, safe_attributes(attributes)))
