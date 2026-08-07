"""Model usage → telemetry (replaces InMemoryUsageRecorder in wired processes).

Emits the §21.3 token metrics with safe, low-cardinality labels. Content never
leaves the process — only counts, providers and versioned identifiers.
"""

from __future__ import annotations

from dataclasses import dataclass

from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.model.gateway import ModelUsage
from dw_agent_runtime.ports import ModelRequest
from dw_observability.metrics import DW_MODEL_COST_USD_TOTAL, DW_MODEL_TOKENS_TOTAL
from dw_observability.telemetry import TelemetryPort


@dataclass(frozen=True)
class TelemetryUsageRecorder:
    """Implements ``UsageRecorderPort`` on the telemetry port."""

    telemetry: TelemetryPort

    def record(self, run_context: RunContext, request: ModelRequest, usage: ModelUsage) -> None:
        labels = {"provider": usage.provider, "model": usage.model}
        self.telemetry.add_metric(
            DW_MODEL_TOKENS_TOTAL, usage.input_tokens, {**labels, "direction": "input"}
        )
        self.telemetry.add_metric(
            DW_MODEL_TOKENS_TOTAL, usage.output_tokens, {**labels, "direction": "output"}
        )
        if usage.cost_usd:
            self.telemetry.add_metric(
                DW_MODEL_COST_USD_TOTAL,
                usage.cost_usd,
                {"worker": run_context.worker_id, "provider": usage.provider},
            )
        with self.telemetry.span(
            "dw.model.call",
            {
                "dw.run_id": str(run_context.run_id),
                "dw.worker_id": run_context.worker_id,
                "dw.prompt_id": request.prompt_id,
                "dw.prompt_version": request.prompt_version,
                "dw.model_profile": request.model_profile,
                "dw.provider": usage.provider,
                "dw.model": usage.model,
                "dw.input_tokens": usage.input_tokens,
                "dw.output_tokens": usage.output_tokens,
                # OTel GenAI semconv mirror: lets Langfuse (via OTLP, ADR-016)
                # recognise the call as a generation and price it from its
                # model table — cost REPORTING without any run-blocking caps.
                "gen_ai.system": usage.provider,
                "gen_ai.request.model": usage.model,
                "gen_ai.response.model": usage.model,
                "gen_ai.usage.input_tokens": usage.input_tokens,
                "gen_ai.usage.output_tokens": usage.output_tokens,
            },
        ):
            pass
