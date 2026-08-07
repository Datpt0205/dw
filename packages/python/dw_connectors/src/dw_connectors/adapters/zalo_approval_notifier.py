"""Zalo DM adapter for DW01 approval notifications — buttonless rendering.

Reuses the channel-neutral ``SlackApprovalMessage`` payload (title, lines,
checkpoint, buttons) but renders everything as plain Vietnamese text with a
"reply in words" instruction instead of interactive buttons; the API-side
``DecisionEngine`` parses those replies ("duyệt cp1", "lập addendum …").
"""

from __future__ import annotations

from dataclasses import dataclass

from dw_connectors.adapters.slack_approval_notifier import (
    SlackApprovalMessage,
    SlackMessageRef,
)
from dw_connectors.adapters.zalo_bot import ZaloBotClient


def _money(message: SlackApprovalMessage) -> str:
    return f"{message.estimated_value_minor:,.0f} {message.currency}".replace(",", ".")


def _reply_hint(message: SlackApprovalMessage) -> str:
    event = message.event_type
    if event in ("intake.approval_requested", "intake.approval_escalated"):
        return "👉 Trả lời: «xác minh» để chạy, hoặc «từ chối» kèm lý do."
    if event == "cp.approval_requested":
        cp = message.checkpoint.lower() or "cp"
        if cp == "cp4":
            return "👉 Trả lời: «xác nhận mở thầu» để chốt sổ và lập biên bản."
        return f"👉 Trả lời: «duyệt {cp}» hoặc «từ chối {cp}»."
    if event == "addendum.proposed":
        return (
            "👉 Trả lời: «lập addendum <nội dung sửa đổi>» để lập và trình CP3, "
            "hoặc «bỏ qua addendum»."
        )
    return ""


def render_text(message: SlackApprovalMessage) -> str:
    """Pure rendering — unit-testable without any network."""
    parts: list[str] = []
    if message.heading:
        parts.append(message.heading)
    parts.append(f"📁 {message.case_title}")
    if message.source_pr_ref:
        parts.append(f"PR: {message.source_pr_ref}")
    if message.owner_name:
        parts.append(f"Người yêu cầu: {message.owner_name}")
    if message.estimated_value_minor:
        parts.append(f"Giá trị dự kiến: {_money(message)}")
    if message.comment:
        parts.append(message.comment)
    for line in message.lines:
        parts.append(f"• {line}")
    hint = _reply_hint(message)
    if hint:
        parts.append("")
        parts.append(hint)
    parts.append(f"🔗 {message.web_url}")
    return "\n".join(parts)


@dataclass(frozen=True)
class ZaloApprovalNotifier:
    """Implements the same ``send`` contract as ``SlackApprovalNotifier``."""

    bot_token: str

    async def send(self, message: SlackApprovalMessage) -> SlackMessageRef:
        client = ZaloBotClient(bot_token=self.bot_token)
        message_id = await client.send_message(
            message.recipient_slack_user_id, render_text(message)
        )
        return SlackMessageRef(channel=message.recipient_slack_user_id, ts=message_id)
