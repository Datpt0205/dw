"""Slack approval DM adapter contract tests without external network calls."""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from typing import Any

import httpx
import pytest

from dw_connectors.adapters.slack_approval_notifier import (
    SlackApprovalMessage,
    SlackApprovalNotifier,
)
from dw_kernel.errors import InfrastructureError

pytestmark = pytest.mark.unit


def _message(event_type: str = "intake.approval_requested") -> SlackApprovalMessage:
    return SlackApprovalMessage(
        message_id=uuid.uuid4(),
        recipient_slack_user_id="U0BINH",
        event_type=event_type,
        case_id=uuid.uuid4(),
        case_title="Mua laptop 2026",
        web_url="http://localhost:3000/procurement/dw01/cases/demo",
        source_pr_ref="PR-2026-001",
        owner_name="Nguyễn Văn An",
        estimated_value_minor=850_000_000,
    )


async def test_opens_dm_and_posts_real_block_kit(monkeypatch) -> None:
    requests: list[tuple[str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append((request.url.path, body))
        if request.url.path.endswith("conversations.open"):
            return httpx.Response(200, json={"ok": True, "channel": {"id": "D0BINH"}})
        return httpx.Response(200, json={"ok": True, "channel": "D0BINH", "ts": "1.002"})

    _patch_client(monkeypatch, handler)
    ref = await SlackApprovalNotifier("xoxb-test").send(_message())

    assert ref.channel == "D0BINH"
    assert ref.ts == "1.002"
    assert [path.rsplit("/", 1)[-1] for path, _ in requests] == [
        "conversations.open",
        "chat.postMessage",
    ]
    assert requests[0][1]["users"] == "U0BINH"
    assert requests[1][1]["client_msg_id"]
    assert any(block.get("type") == "actions" for block in requests[1][1]["blocks"])


async def test_slack_api_rejection_preserves_provider_error_code(monkeypatch) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "error": "missing_scope"})

    _patch_client(monkeypatch, handler)
    with pytest.raises(InfrastructureError, match="rejected") as caught:
        await SlackApprovalNotifier("xoxb-test").send(_message())
    assert caught.value.details["slack_error"] == "missing_scope"


async def test_invalid_member_id_is_rejected_before_network() -> None:
    invalid = replace(
        _message(),
        recipient_slack_user_id="binh@example.com",
    )
    with pytest.raises(InfrastructureError, match="member ID") as caught:
        await SlackApprovalNotifier("xoxb-test").send(invalid)
    assert caught.value.details["slack_error"] == "invalid_member_id"


def _patch_client(monkeypatch, handler) -> None:
    real_init = httpx.AsyncClient.__init__

    def fake_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", fake_init)


def test_render_run_progress_card() -> None:
    from dw_connectors.adapters.slack_approval_notifier import SlackApprovalMessage, _render

    text, blocks = _render(
        SlackApprovalMessage(
            message_id=uuid.uuid4(),
            recipient_slack_user_id="U123",
            event_type="run.progress",
            case_id=uuid.uuid4(),
            case_title="Mua 100 laptop",
            web_url="http://localhost:3000/procurement/dw01/cases/x",
            heading="Gate CP1: ĐẠT — chờ Quản lý phê duyệt",
            lines=("Giá trị 2 tỷ → Đấu thầu", "Đã trình duyệt CP1"),
        )
    )
    assert "Gate CP1" in text
    body = blocks[1]["text"]["text"]
    # Everything stays in the open — actionable lines must never hide.
    assert "• Giá trị 2 tỷ" in body and "• Đã trình duyệt CP1" in body
    assert blocks[2]["elements"][0]["url"].endswith("/cases/x")
