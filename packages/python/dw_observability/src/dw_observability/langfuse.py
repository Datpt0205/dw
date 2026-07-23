"""Langfuse integration behind configuration (blueprint §21.4).

Langfuse v3 ingests standard OTLP traces, so the "adapter" is an exporter
configuration, not another SDK: point ``configure_tracing`` at the Langfuse
OTLP endpoint with Basic auth derived from the project keys.
"""

from __future__ import annotations

import base64

_OTEL_TRACES_PATH = "/api/public/otel/v1/traces"


def langfuse_otlp_config(host: str, public_key: str, secret_key: str) -> tuple[str, dict[str, str]]:
    """Build (endpoint, headers) for OTLP export into Langfuse."""
    if not host.startswith(("http://", "https://")):
        raise ValueError("LANGFUSE_HOST must include the scheme, e.g. https://cloud.langfuse.com")
    if not public_key or not secret_key:
        raise ValueError("Langfuse requires both public and secret keys")
    token = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode("ascii")
    return host.rstrip("/") + _OTEL_TRACES_PATH, {"Authorization": f"Basic {token}"}
