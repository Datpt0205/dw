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
    # run.progress cards (P3 activity trace): system-built heading + bullets.
    heading: str = ""
    lines: tuple[str, ...] = ()
    # P4: interactive buttons [{action_id, label, value, style?}]. Rendering
    # only — every click is re-authorized server-side via the normal handlers.
    buttons: tuple[dict[str, str], ...] = ()
    checkpoint: str = ""


@dataclass(frozen=True, slots=True)
class SlackMessageRef:
    channel: str
    ts: str


def _money(message: SlackApprovalMessage) -> str:
    return f"{message.estimated_value_minor:,.0f} {message.currency}".replace(",", ".")


def _action_buttons(message: SlackApprovalMessage) -> list[dict[str, Any]]:
    elements: list[dict[str, Any]] = []
    for button in message.buttons:
        element: dict[str, Any] = {
            "type": "button",
            "text": {"type": "plain_text", "text": button.get("label", "—"), "emoji": True},
            "action_id": button.get("action_id", ""),
            "value": button.get("value", ""),
        }
        if button.get("style") in ("primary", "danger"):
            element["style"] = button["style"]
        elements.append(element)
    return elements


def _link_button(message: SlackApprovalMessage, label: str = "Mở hồ sơ DW01") -> dict[str, Any]:
    return {
        "type": "button",
        "text": {"type": "plain_text", "text": label, "emoji": True},
        "url": message.web_url,
        "action_id": "open_dw01_case",
    }


def _render(
    message: SlackApprovalMessage,
) -> tuple[str, list[dict[str, Any]], tuple[str, ...]]:
    """Render a card. Returns (fallback_text, blocks, detail_lines).

    ``detail_lines`` are posted as a THREAD reply so the DM reads like an
    activity feed (one short status line per step); clicking the message
    expands the details — the Slack-native version of a collapsible block.
    """
    event = message.event_type
    if event == "run.progress":
        heading = message.heading or "Cập nhật tiến trình"
        visible = message.lines[:1]
        details = tuple(message.lines[1:])
        body = f"*{message.case_title}*" + "".join(f"\n• {line}" for line in visible)
        context = (
            "Bấm vào tin nhắn để xem chi tiết trong thread."
            if details
            else "Ngọc cập nhật tiến độ."
        )
        text = f"{heading}: {message.case_title}"
        blocks: list[dict[str, Any]] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*{heading}*"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": body}},
            {
                "type": "actions",
                "elements": [*_action_buttons(message), _link_button(message)],
            },
            {"type": "context", "elements": [{"type": "mrkdwn", "text": context}]},
        ]
        return text, blocks, details
    if event == "cp.approval_requested":
        cp = message.checkpoint or "CP"
        cp_label = {
            "CP1": "CP1 — Duyệt phương án mua sắm",
            "CP2": "CP2 — Duyệt hồ sơ trước phát hành",
            "CP3": "CP3 — Duyệt làm rõ/sửa đổi sau phát hành",
            "CP4": "CP4 — Xác nhận mở thầu & bàn giao DW02",
        }.get(cp, cp)
        heading = f"🔔 {cp_label}: chờ bạn quyết định"
        # Keep the two key facts on the card; the regulation/review detail
        # expands in the thread (activity-feed style).
        cp_visible = message.lines[:2]
        cp_details = tuple(message.lines[2:])
        body = f"*{message.case_title}*" + "".join(f"\n• {line}" for line in cp_visible)
        text = f"{heading} — {message.case_title}"
        if cp == "CP4":
            decision_elements: list[dict[str, Any]] = [
                {
                    "type": "button",
                    "style": "primary",
                    "text": {
                        "type": "plain_text",
                        "text": "✅ Xác nhận mở thầu & bàn giao",
                        "emoji": True,
                    },
                    "action_id": "dw01_cp4_confirm",
                    "value": str(message.case_id),
                },
            ]
        else:
            decision_elements = [
                {
                    "type": "button",
                    "style": "primary",
                    "text": {"type": "plain_text", "text": f"✅ Duyệt {cp}", "emoji": True},
                    "action_id": "dw01_cp_approve",
                    "value": f"{cp.lower()}:{message.case_id}",
                },
                {
                    "type": "button",
                    "style": "danger",
                    "text": {"type": "plain_text", "text": "❌ Từ chối", "emoji": True},
                    "action_id": "dw01_cp_reject",
                    "value": f"{cp.lower()}:{message.case_id}",
                },
            ]
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*{heading}*"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": body}},
            {
                "type": "actions",
                "elements": [*decision_elements, _link_button(message, "Xem chi tiết")],
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            "Quyết định được ghi nhận với danh tính của bạn và "
                            "lưu vào audit — người tạo hồ sơ không thể tự duyệt (SoD)."
                            + (" Chi tiết đối chiếu: trong thread." if cp_details else "")
                        ),
                    }
                ],
            },
        ]
        return text, blocks, cp_details
    if event == "intake.approval_requested":
        heading = "Yêu cầu mới cần phê duyệt"
        body = (
            f"*{message.case_title}*\n"
            f"Người tạo: {message.owner_name or '—'}\n"
            f"PR: `{message.source_pr_ref or '—'}` · Giá trị: {_money(message)}"
        )
        context = "Bấm nút để quyết định ngay tại đây — hoặc mở hồ sơ xem chi tiết trước."
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
        context = "Mình sẽ bắt đầu xử lý và báo tiến độ tại đây."
    elif event == "intake.rejected":
        heading = "Hồ sơ không được phê duyệt"
        body = (
            f"*{message.case_title}* đã bị từ chối.\nLý do: {message.comment or 'Không có lý do'}"
        )
        context = "Mở hồ sơ để xem trạng thái và chuẩn bị lại dữ liệu đầu vào."
    else:
        raise InfrastructureError("unsupported Slack approval event", details={"event_type": event})
    text = f"{heading}: {message.case_title}"
    # P4: the intake request card carries decision buttons so the approver never
    # needs the web UI. Clicks are re-authorized server-side (identity → scopes).
    action_elements: list[dict[str, Any]] = []
    if event == "intake.approval_requested":
        action_elements = [
            {
                "type": "button",
                "style": "primary",
                "text": {"type": "plain_text", "text": "✅ Xác minh & chạy DW01", "emoji": True},
                "action_id": "dw01_intake_approve",
                "value": str(message.case_id),
            },
            {
                "type": "button",
                "style": "danger",
                "text": {"type": "plain_text", "text": "❌ Từ chối", "emoji": True},
                "action_id": "dw01_intake_reject",
                "value": str(message.case_id),
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "📄 Xem PR", "emoji": True},
                "action_id": "dw01_view_pr",
                "value": str(message.case_id),
            },
        ]
    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": heading, "emoji": True},
        },
        {"type": "section", "text": {"type": "mrkdwn", "text": body}},
        {
            "type": "actions",
            "elements": [
                *action_elements,
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Mở hồ sơ DW01", "emoji": True},
                    "url": message.web_url,
                    "action_id": "open_dw01_case",
                },
            ],
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": context}],
        },
    ]
    return text, blocks, ()


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
        text, blocks, detail_lines = _render(message)
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
            ts = str(posted.get("ts", ""))
            # Details collapse behind the status line: posted as a thread
            # reply so the DM stays a clean activity feed (click to expand).
            if detail_lines and ts:
                await self._call(
                    client,
                    "/chat.postMessage",
                    {
                        "channel": channel,
                        "thread_ts": ts,
                        "text": "Chi tiết bước này",
                        "blocks": [
                            {
                                "type": "section",
                                "text": {
                                    "type": "mrkdwn",
                                    "text": "\n".join(f"• {line}" for line in detail_lines),
                                },
                            },
                            {
                                "type": "context",
                                "elements": [
                                    {
                                        "type": "mrkdwn",
                                        "text": (
                                            "Xem căn cứ đầy đủ trên web — mục "
                                            "«Vết thực thi» của hồ sơ."
                                        ),
                                    }
                                ],
                            },
                        ],
                        "unfurl_links": False,
                        "unfurl_media": False,
                    },
                )
        return SlackMessageRef(channel=channel, ts=ts)

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
