"""Slack DM adapter for durable DW01 approval lifecycle notifications."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from dw_kernel.errors import InfrastructureError
from dw_kernel.net_guard import ensure_allowed_outbound_url

_API_BASE = "https://slack.com/api"


@dataclass(frozen=True, slots=True)
class SlackApprovalMessage:
    message_id: uuid.UUID
    recipient_slack_user_id: str
    event_type: str
    case_id: uuid.UUID
    case_title: str
    web_url: str
    source_pr_ref: str = ""
    owner_name: str = ""
    estimated_value_minor: int = 0
    currency: str = "VND"
    comment: str = ""


@dataclass(frozen=True, slots=True)
class SlackMessageRef:
    channel: str
    ts: str


def _money(message: SlackApprovalMessage) -> str:
    return f"{message.estimated_value_minor:,.0f} {message.currency}".replace(",", ".")


def _render(message: SlackApprovalMessage) -> tuple[str, list[dict[str, Any]]]:
    event = message.event_type
    if event == "intake.approval_requested":
        heading = "Yêu cầu mới cần phê duyệt"
        body = (
            f"*{message.case_title}*\n"
            f"Người tạo: {message.owner_name or '—'}\n"
            f"PR: `{message.source_pr_ref or '—'}` · Giá trị: {_money(message)}"
        )
        context = "Vui lòng mở DW01 bằng tài khoản approver để phê duyệt hoặc từ chối."
    elif event == "intake.approval_escalated":
        heading = "Nhắc việc phê duyệt quá hạn"
        body = (
            f"*{message.case_title}* vẫn đang chờ Bình xử lý.\n"
            "Chi vui lòng nhắc người phê duyệt để quy trình của An có thể tiếp tục."
        )
        context = "Hệ thống đã kiểm tra lại trạng thái ngay trước khi gửi nhắc."
    elif event == "intake.approved":
        heading = "Hồ sơ đã được phê duyệt"
        body = f"*{message.case_title}* đã qua bước kiểm tra intake."
        context = "Bạn có thể mở hồ sơ và chạy Digital Worker DW01."
    elif event == "intake.rejected":
        heading = "Hồ sơ không được phê duyệt"
        body = (
            f"*{message.case_title}* đã bị từ chối.\nLý do: {message.comment or 'Không có lý do'}"
        )
        context = "Mở hồ sơ để xem trạng thái và chuẩn bị lại dữ liệu đầu vào."
    else:
        raise InfrastructureError("unsupported Slack approval event", details={"event_type": event})
    text = f"{heading}: {message.case_title}"
    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": heading, "emoji": True},
        },
        {"type": "section", "text": {"type": "mrkdwn", "text": body}},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Mở hồ sơ DW01", "emoji": True},
                    "url": message.web_url,
                    "action_id": "open_dw01_case",
                }
            ],
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": context}],
        },
    ]
    return text, blocks


@dataclass
class SlackApprovalNotifier:
    bot_token: str
    timeout_seconds: float = 15.0

    def __post_init__(self) -> None:
        if not self.bot_token.startswith("xoxb-"):
            raise InfrastructureError("SLACK_BOT_TOKEN missing or not a bot token (xoxb-...)")
        ensure_allowed_outbound_url(_API_BASE)

    async def send(self, message: SlackApprovalMessage) -> SlackMessageRef:
        if not message.recipient_slack_user_id.startswith(("U", "W")):
            raise InfrastructureError(
                "invalid Slack member ID",
                details={
                    "slack_error": "invalid_member_id",
                    "member_id": message.recipient_slack_user_id[:16],
                },
            )
        text, blocks = _render(message)
        async with httpx.AsyncClient(
            base_url=_API_BASE,
            headers={"Authorization": f"Bearer {self.bot_token}"},
            timeout=self.timeout_seconds,
        ) as client:
            channel_data = await self._call(
                client,
                "/conversations.open",
                {"users": message.recipient_slack_user_id, "return_im": True},
            )
            channel = str(channel_data.get("channel", {}).get("id", ""))
            if not channel:
                raise InfrastructureError("Slack did not return a DM channel")
            posted = await self._call(
                client,
                "/chat.postMessage",
                {
                    "channel": channel,
                    "text": text,
                    "blocks": blocks,
                    "unfurl_links": False,
                    "unfurl_media": False,
                    # Slack uses this UUID to deduplicate accidental replays.
                    "client_msg_id": str(message.message_id),
                },
            )
        return SlackMessageRef(channel=channel, ts=str(posted.get("ts", "")))

    @staticmethod
    async def _call(
        client: httpx.AsyncClient, endpoint: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            response = await client.post(endpoint, json=payload)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise InfrastructureError(
                "Slack request failed", details={"endpoint": endpoint}
            ) from exc
        if not data.get("ok"):
            raise InfrastructureError(
                "Slack rejected the request",
                details={
                    "endpoint": endpoint,
                    "slack_error": str(data.get("error", "unknown")),
                },
            )
        return dict(data)
