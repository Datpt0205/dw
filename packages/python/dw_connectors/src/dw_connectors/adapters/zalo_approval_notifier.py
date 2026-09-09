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
    if event == "law.change_detected":
        # No verb here on purpose. Nothing was undone and nothing is owed — the
        # card reports a fact, and offers the amendment path for whoever decides
        # the fact matters.
        return "👉 Muốn áp mốc mới: «sửa hồ sơ <tên> thời hạn <số> ngày»."
    if event == "rework.support_offered":
        # Nothing is owed and nothing is blocked. The verb is an offer.
        return "👉 Cần hỗ trợ thì mở hồ sơ và mô tả giúp phần đang vướng nhé."
    if event == "rework.support_required":
        return "👉 Mở hồ sơ để xem phần mô tả bối cảnh và trao đổi giúp."
    if event == "intake_quota.justification_submitted":
        # The decision is a person's, so the verb has to be theirs. Approving
        # lets the next request through; nothing happens on its own.
        return "👉 Trả lời: «duyệt giải trình» hoặc «từ chối giải trình»."
    if event == "rework.explanation_escalated":
        return "👉 Nhờ bạn phân công người xem giúp phần mô tả này."
    return ""


def render_text(message: SlackApprovalMessage) -> str:
    """Pure rendering — unit-testable without any network."""
    parts: list[str] = []
    if message.heading:
        parts.append(message.heading)
    parts.append(f"📁 {message.case_title}")
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
