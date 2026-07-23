"""Slack task connector: dispatch approved action items as Slack messages.

Anti-corruption: the canonical ``CreateExternalTask`` is rendered into Slack
Block Kit here; Slack payloads never leak upward. Idempotency: replaying the
same key returns the original ``channel:ts`` reference without reposting.
The circuit breaker trips on repeated infrastructure failures only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

from dw_connectors.contracts import CreateExternalTask, ExternalTaskRef
from dw_kernel.errors import IdempotencyConflictError, InfrastructureError
from dw_kernel.net_guard import ensure_allowed_outbound_url
from dw_kernel.resilience import CircuitBreaker

CONNECTOR_NAME = "slack"
CONNECTOR_VERSION = "1.0.0"
_API_BASE = "https://slack.com/api"


def _blocks(command: CreateExternalTask) -> list[dict[str, object]]:
    due = command.due_date.strftime("%d/%m/%Y") if command.due_date else "chưa đặt"
    lines = [
        f"*{command.title}*",
        command.description or "_không có mô tả_",
        f"👤 *Phụ trách:* {command.assignee.display_name}   📅 *Hạn:* {due}",
    ]
    return [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(lines)},
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        "Giao việc bởi Digital Worker sau khi được phê duyệt · "
                        f"action `{command.action_item_id}`"
                    ),
                }
            ],
        },
    ]


@dataclass
class SlackTaskConnectorAdapter:
    """Implements ``TaskConnectorPort`` over the Slack Web API."""

    bot_token: str
    default_channel: str
    timeout_seconds: float = 15.0
    breaker: CircuitBreaker | None = None
    # In-process replay guard; the durable one is platform.tool_executions.
    _store: dict[str, tuple[str, ExternalTaskRef]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.bot_token or not self.bot_token.startswith("xoxb-"):
            raise InfrastructureError("SLACK_BOT_TOKEN missing or not a bot token (xoxb-...)")
        if not self.default_channel:
            raise InfrastructureError("SLACK_DEFAULT_CHANNEL is required")
        ensure_allowed_outbound_url(_API_BASE)  # public host; SSRF fail-closed

    @property
    def connector_name(self) -> str:
        return CONNECTOR_NAME

    async def create_task(
        self,
        command: CreateExternalTask,
        idempotency_key: str,
    ) -> ExternalTaskRef:
        fingerprint = command.model_dump_json()
        existing = self._store.get(idempotency_key)
        if existing is not None:
            stored_fingerprint, stored_ref = existing
            if stored_fingerprint != fingerprint:
                raise IdempotencyConflictError(
                    "idempotency key reused with a different payload",
                    details={"idempotency_key": idempotency_key},
                )
            return stored_ref

        # Slack user id (if mapped in the org directory) → DM mention in text.
        slack_user = command.assignee.external_identities.get("slack")
        text = f"Việc mới cho {command.assignee.display_name}: {command.title}"
        if slack_user:
            text = f"<@{slack_user}> {text}"

        if self.breaker is not None:
            self.breaker.before_call()
        try:
            async with httpx.AsyncClient(
                base_url=_API_BASE,
                headers={"Authorization": f"Bearer {self.bot_token}"},
                timeout=self.timeout_seconds,
            ) as client:
                response = await client.post(
                    "/chat.postMessage",
                    json={
                        "channel": self.default_channel,
                        "text": text,
                        "blocks": _blocks(command),
                        "unfurl_links": False,
                    },
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            if self.breaker is not None:
                self.breaker.record_failure()
            raise InfrastructureError(
                "slack request failed",
                details={"error": type(exc).__name__},
            ) from exc

        if not data.get("ok"):
            # API-level rejection (bad channel/scope) — not a breaker trip.
            raise InfrastructureError(
                "slack rejected the message",
                details={"slack_error": str(data.get("error", "unknown"))},
            )
        if self.breaker is not None:
            self.breaker.record_success()

        channel = str(data.get("channel", self.default_channel))
        ts = str(data.get("ts", ""))
        ref = ExternalTaskRef(
            connector=CONNECTOR_NAME,
            connector_version=CONNECTOR_VERSION,
            external_id=f"{channel}:{ts}",
            external_url=(
                f"https://app.slack.com/client/{channel}"
                if not ts
                else f"https://slack.com/archives/{channel}/p{ts.replace('.', '')}"
            ),
            created_at=datetime.now(tz=UTC),
        )
        self._store[idempotency_key] = (fingerprint, ref)
        return ref
