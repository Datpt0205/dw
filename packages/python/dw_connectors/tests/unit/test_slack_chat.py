"""Socket Mode frame handling: ack-fast, dispatch async, reconnect on demand."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field

import pytest

from dw_connectors.adapters.slack_chat import SlackChatClient, SlackSocketModeRunner
from dw_kernel.errors import InfrastructureError

pytestmark = pytest.mark.unit


@dataclass
class FakeWs:
    sent: list[str] = field(default_factory=list)

    async def send(self, data: str) -> None:
        self.sent.append(data)


def make_runner(handled: list[dict]) -> SlackSocketModeRunner:
    async def handler(envelope: dict) -> None:
        handled.append(envelope)

    return SlackSocketModeRunner(app_token="xapp-1-TEST", handler=handler)


def test_bot_token_type_is_validated() -> None:
    with pytest.raises(InfrastructureError):
        SlackChatClient(bot_token="xoxp-user-token")
    with pytest.raises(InfrastructureError):
        SlackSocketModeRunner(app_token="xoxb-not-app", handler=None)  # type: ignore[arg-type]


async def test_hello_frame_is_ignored() -> None:
    ws = FakeWs()
    runner = make_runner([])
    reconnect = await runner._on_frame(ws, json.dumps({"type": "hello"}))
    assert reconnect is False and ws.sent == []


async def test_disconnect_frame_requests_reconnect() -> None:
    ws = FakeWs()
    runner = make_runner([])
    reconnect = await runner._on_frame(
        ws, json.dumps({"type": "disconnect", "reason": "refresh_requested"})
    )
    assert reconnect is True


async def test_events_api_envelope_is_acked_then_dispatched() -> None:
    ws = FakeWs()
    handled: list[dict] = []
    runner = make_runner(handled)
    envelope = {
        "type": "events_api",
        "envelope_id": "env-1",
        "payload": {"event_id": "Ev1", "event": {"type": "message", "text": "hi"}},
    }
    await runner._on_frame(ws, json.dumps(envelope))
    # ACK was sent synchronously with the envelope id.
    assert json.loads(ws.sent[0]) == {"envelope_id": "env-1"}
    # Handler runs asynchronously.
    await asyncio.sleep(0)
    assert handled and handled[0]["envelope_id"] == "env-1"


async def test_handler_error_does_not_propagate() -> None:
    async def boom(_: dict) -> None:
        raise RuntimeError("bad payload")

    runner = SlackSocketModeRunner(app_token="xapp-1-TEST", handler=boom)
    ws = FakeWs()
    await runner._on_frame(
        ws, json.dumps({"type": "interactive", "envelope_id": "env-2", "payload": {}})
    )
    await asyncio.sleep(0)  # let the task run; exception must be swallowed


async def test_malformed_json_is_ignored() -> None:
    runner = make_runner([])
    assert await runner._on_frame(FakeWs(), "not-json{") is False
