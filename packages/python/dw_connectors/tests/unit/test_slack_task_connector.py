"""Slack connector: payload shape, idempotent replay, failure taxonomy."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from dw_connectors.adapters.slack_task_connector import SlackTaskConnectorAdapter
from dw_connectors.contracts import CreateExternalTask, OrganizationPersonRef
from dw_kernel.errors import IdempotencyConflictError, InfrastructureError

pytestmark = pytest.mark.unit

TOKEN = "xoxb-test-token"


def command(title: str = "Soạn hồ sơ RFQ") -> CreateExternalTask:
    return CreateExternalTask(
        tenant_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        action_item_id=uuid.uuid4(),
        title=title,
        description="Hạn chót sáng 30/07",
        assignee=OrganizationPersonRef(
            person_id=uuid.uuid4(),
            display_name="Trần Thị Bình",
            external_identities={"slack": "U0BINH"},
        ),
        due_date=datetime(2026, 7, 30, tzinfo=UTC),
    )


async def test_posts_block_kit_and_returns_channel_ts(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers["Authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True, "channel": "C0DEMO", "ts": "1721.001"})

    _patch_client(monkeypatch, handler)
    connector = SlackTaskConnectorAdapter(bot_token=TOKEN, default_channel="C0DEMO")
    ref = await connector.create_task(command(), "key-1")

    assert captured["auth"] == f"Bearer {TOKEN}"
    assert captured["body"]["channel"] == "C0DEMO"
    assert "<@U0BINH>" in captured["body"]["text"]
    assert any(
        "Trần Thị Bình" in json.dumps(b, ensure_ascii=False) for b in captured["body"]["blocks"]
    )
    assert ref.connector == "slack"
    assert ref.external_id == "C0DEMO:1721.001"


async def test_idempotent_replay_does_not_repost(monkeypatch) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"ok": True, "channel": "C0DEMO", "ts": "1721.002"})

    _patch_client(monkeypatch, handler)
    connector = SlackTaskConnectorAdapter(bot_token=TOKEN, default_channel="C0DEMO")
    cmd = command()
    first = await connector.create_task(cmd, "key-2")
    second = await connector.create_task(cmd, "key-2")
    assert calls["n"] == 1
    assert first == second

    conflicting = cmd.model_copy(update={"title": "Khác hẳn"})
    with pytest.raises(IdempotencyConflictError):
        await connector.create_task(conflicting, "key-2")


async def test_slack_api_error_raises_infrastructure(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "error": "channel_not_found"})

    _patch_client(monkeypatch, handler)
    connector = SlackTaskConnectorAdapter(bot_token=TOKEN, default_channel="C0DEMO")
    with pytest.raises(InfrastructureError, match="rejected"):
        await connector.create_task(command(), "key-3")


def test_invalid_config_fails_fast() -> None:
    with pytest.raises(InfrastructureError, match="SLACK_BOT_TOKEN"):
        SlackTaskConnectorAdapter(bot_token="not-a-bot-token", default_channel="C0")
    with pytest.raises(InfrastructureError, match="SLACK_DEFAULT_CHANNEL"):
        SlackTaskConnectorAdapter(bot_token=TOKEN, default_channel="")


def _patch_client(monkeypatch, handler) -> None:
    """Route the adapter's AsyncClient through a mock transport."""
    real_init = httpx.AsyncClient.__init__

    def fake_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", fake_init)
