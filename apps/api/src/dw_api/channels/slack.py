"""Slack front office for DW01: chat intake over Socket Mode.

Mirrors the Telegram channel's trust path (chat is intake/notify only, never
authorization): Slack member ID → demo subject via configuration → the normal
DB membership check builds the AccessContext. The conversation logic itself is
channel-agnostic (``ConversationIntakeService``); this module only translates
Slack payloads ↔ neutral replies and renders Block Kit.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import yaml

from dw_platform.application.access_context import AccessContext
from dw_platform.application.identity import VerifiedClaims

if TYPE_CHECKING:
    from dw_api.bootstrap import ApiContainer, ChatFrontOffice

logger = logging.getLogger("dw_api.channels.slack")

_CONFIRM_ACTION = "dw01_chat_confirm"
_EDIT_ACTION = "dw01_chat_edit"
# P4: decision/publication buttons on worker-sent cards.
_INTAKE_APPROVE = "dw01_intake_approve"
_INTAKE_REJECT = "dw01_intake_reject"
_CP_APPROVE = "dw01_cp_approve"
_CP_REJECT = "dw01_cp_reject"
_PUBLISH = "dw01_publish"

# Slack section blocks cap at 3000 chars; keep the thinking readable.
_THINKING_MAX_CHARS = 2200


@dataclass
class SlackFrontOfficeService:
    """Handles Socket Mode envelopes end to end."""

    container: ApiContainer
    chat: ChatFrontOffice
    repo_root: Path

    # ------------------------------------------------------------- identity --
    def _resolve_subject(self, slack_user_id: str) -> str | None:
        # 1) configs/demo/channel_identities.yaml `slack:` section (optional)…
        path = self.repo_root / "configs" / "demo" / "channel_identities.yaml"
        if path.exists():
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            mapping = raw.get("slack") or {}
            if mapping.get(slack_user_id):
                return str(mapping[slack_user_id])
        # 2) …falling back to the same env map used for outbound notifications.
        return self.chat.slack_user_reverse_map.get(slack_user_id)

    def _roster_entry(self, subject: str) -> dict[str, Any] | None:
        path = self.repo_root / "configs" / "demo" / "demo_users.yaml"
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        for user in raw.get("users", []):
            if user["subject"] == subject:
                return dict(user)
        return None

    async def _access_context(self, subject: str) -> tuple[AccessContext, str] | None:
        entry = self._roster_entry(subject)
        factory = self.container.access_context_factory
        if entry is None or factory is None:
            return None
        context = await factory.build(
            VerifiedClaims(subject=subject, email=None, issuer="dw-slack"),
            UUID(str(entry["tenant_id"])),
            UUID(str(entry["workspace_id"])),
        )
        return context, str(entry.get("display_name", subject))

    # ------------------------------------------------------------- envelope --
    async def handle_envelope(self, envelope: dict[str, Any]) -> None:
        kind = envelope.get("type")
        payload = envelope.get("payload") or {}
        if kind == "events_api":
            await self._handle_event(payload)
        elif kind == "interactive":
            await self._handle_interactive(payload)

    async def _handle_event(self, payload: dict[str, Any]) -> None:
        event = payload.get("event") or {}
        if event.get("type") not in ("message", "app_mention"):
            return
        if event.get("bot_id") or event.get("subtype"):
            return  # never react to bots (incl. ourselves) or edits/joins
        # message events only from DMs; channel chatter requires @mention.
        if event.get("type") == "message" and event.get("channel_type") != "im":
            return

        event_id = str(payload.get("event_id") or "")
        if event_id and not await self.chat.conversation_store.claim_event(f"slack:{event_id}"):
            return  # redelivery

        channel = str(event.get("channel", ""))
        user = str(event.get("user", ""))
        text = str(event.get("text", "")).strip()
        thread_ts = event.get("thread_ts")
        if not channel or not user or not text:
            return

        subject = self._resolve_subject(user)
        if subject is None:
            await self.chat.chat_client.post_message(
                channel=channel,
                thread_ts=thread_ts,
                text=(
                    f"👋 Slack ID của bạn là `{user}` — chưa được gán với người dùng DW.\n"
                    "Nhờ quản trị viên thêm ID này vào cấu hình "
                    "(SLACK_USER_*_ID trong .env hoặc configs/demo/channel_identities.yaml)."
                ),
            )
            return
        resolved = await self._access_context(subject)
        if resolved is None:
            logger.warning("slack subject %s not in roster/membership", subject)
            return
        context, display_name = resolved

        # DM = one rolling conversation per channel; channel mention = per thread.
        channel_key = f"slack:{channel}" + (f":{thread_ts}" if thread_ts else "")

        # Thinking-first UX: post a placeholder immediately (the reasoner can
        # take a while), then replace it with the model's visible reasoning
        # BEFORE the actual replies arrive as separate messages.
        thinking_ts = await self.chat.chat_client.post_message(
            channel=channel, thread_ts=thread_ts, text="🤔 Đang suy nghĩ…"
        )
        try:
            outcome = await self.chat.conversation_service.handle_message(
                channel_key=channel_key,
                text=self._strip_mention(text),
                context=context,
                display_name=display_name,
            )
        except Exception:
            await self.chat.chat_client.update_message(
                channel=channel,
                ts=thinking_ts,
                text="⚠️ Xin lỗi, tôi gặp trục trặc khi xử lý — bạn nhắn lại giúp nhé.",
            )
            raise
        await self._reveal_thinking(channel, thinking_ts, outcome.thinking)
        for reply in outcome.replies:
            await self._send_reply(channel, thread_ts, reply)

    async def _handle_interactive(self, payload: dict[str, Any]) -> None:
        if payload.get("type") != "block_actions":
            return
        actions = payload.get("actions") or []
        if not actions:
            return
        action_id = str(actions[0].get("action_id", ""))
        known = (
            _CONFIRM_ACTION,
            _EDIT_ACTION,
            _INTAKE_APPROVE,
            _INTAKE_REJECT,
            _CP_APPROVE,
            _CP_REJECT,
            _PUBLISH,
        )
        if action_id not in known:
            return
        value = str(actions[0].get("value", ""))
        user = str((payload.get("user") or {}).get("id", ""))
        channel = str((payload.get("channel") or {}).get("id", ""))
        message = payload.get("message") or {}

        subject = self._resolve_subject(user)
        if subject is None or not channel:
            return
        resolved = await self._access_context(subject)
        if resolved is None:
            return
        context, display_name = resolved

        if action_id in (_INTAKE_APPROVE, _INTAKE_REJECT, _CP_APPROVE, _CP_REJECT, _PUBLISH):
            await self._handle_decision_action(
                action_id=action_id,
                value=value,
                channel=channel,
                message=message,
                context=context,
                display_name=display_name,
            )
            return

        try:
            conv_uuid = UUID(value)
        except ValueError:
            return
        outcome = await self.chat.conversation_service.handle_action(
            action="confirm" if action_id == _CONFIRM_ACTION else "edit",
            conversation_id=conv_uuid,
            context=context,
            display_name=display_name,
        )
        # Disable the stale buttons on the original card.
        if message.get("ts"):
            chosen = "✅ Đã xác nhận" if action_id == _CONFIRM_ACTION else "✏️ Đang sửa thông tin"
            await self.chat.chat_client.update_message(
                channel=channel, ts=str(message["ts"]), text=f"{chosen} — xem tin nhắn tiếp theo."
            )
        thread_ts = message.get("thread_ts")
        for reply in outcome.replies:
            await self._send_reply(channel, thread_ts, reply)

    # ------------------------------------------------- decision buttons (P4) --
    async def _handle_decision_action(
        self,
        *,
        action_id: str,
        value: str,
        channel: str,
        message: dict[str, Any],
        context: AccessContext,
        display_name: str,
    ) -> None:
        """Intake verify / CP1-CP2 decide / publish — driven from Slack cards.

        Slack chỉ là kênh: mọi call đi qua đúng application handler với
        AccessContext thật của người bấm (scope + SoD + RLS đều được kiểm tra
        lại phía server; thiếu quyền → từ chối, không leo thang).
        """
        preparation = self.container.preparation
        if preparation is None:
            return
        try:
            reply = await self._execute_decision(action_id, value, context, display_name)
        except Exception as exc:
            logger.warning("slack decision failed action=%s: %s", action_id, exc)
            reply = f"⚠️ Không thực hiện được: {str(exc)[:300]}"
        if message.get("ts"):
            await self.chat.chat_client.update_message(
                channel=channel,
                ts=str(message["ts"]),
                text="🕘 Đã ghi nhận thao tác — kết quả ở tin nhắn tiếp theo.",
            )
        await self.chat.chat_client.post_message(channel=channel, text=reply)

    async def _execute_decision(
        self, action_id: str, value: str, context: AccessContext, display_name: str
    ) -> str:
        preparation = self.container.preparation
        assert preparation is not None
        now = datetime.now(tz=UTC)

        if action_id in (_INTAKE_APPROVE, _INTAKE_REJECT):
            case_id = UUID(value)
            if action_id == _INTAKE_APPROVE:
                await preparation.verify_intake.handle(
                    case_id,
                    approval_reference=f"SLACK-{now:%Y%m%d-%H%M%S}",
                    comment=f"Xác minh qua Slack bởi {display_name}",
                    context=context,
                )
                return (
                    "✅ Đã xác minh intake — Digital Worker bắt đầu chạy. "
                    "Người tạo hồ sơ sẽ nhận tiến độ từng bước."
                )
            await preparation.reject_intake.handle(
                case_id, comment=f"Từ chối qua Slack bởi {display_name}", context=context
            )
            return "❌ Đã từ chối hồ sơ — người tạo sẽ nhận thông báo kèm lý do."

        if action_id in (_CP_APPROVE, _CP_REJECT):
            cp, _, case_raw = value.partition(":")
            case_id = UUID(case_raw)
            approve = action_id == _CP_APPROVE
            if cp == "cp3":
                # CP3 is a domain decision (no LangGraph interrupt behind it).
                await preparation.decide_cp3.handle(
                    case_id,
                    approve=approve,
                    approval_reference=f"SLACK-{now:%Y%m%d-%H%M%S}",
                    comment=f"Quyết định qua Slack bởi {display_name}",
                    context=context,
                )
                return (
                    "✅ Đã duyệt CP3 — addendum có hiệu lực."
                    if approve
                    else "⛔ Đã từ chối CP3 — HSMT giữ nguyên."
                )
            approval_id = await self._find_pending_approval(cp, case_id, context)
            if approval_id is None:
                return (
                    "⚠️ Không còn yêu cầu phê duyệt đang chờ cho checkpoint này "
                    "(có thể đã được quyết định)."
                )
            await self.container.approval_flow.decide(  # type: ignore[union-attr]
                approval_id=approval_id,
                approve=approve,
                comment=f"Quyết định qua Slack bởi {display_name}",
                context=context,
                authorization=self.container.authorization,
            )
            label = cp.upper()
            if approve:
                return f"✅ Đã duyệt {label} — quy trình tiếp tục chạy tự động."
            return f"⛔ Đã từ chối {label} — quy trình dừng, người tạo sẽ được thông báo."

        if action_id == _PUBLISH:
            case_id = UUID(value)
            result = await preparation.auto_publish.handle(case_id, context)
            recipient = str(result.get("recipient", "")) if isinstance(result, dict) else ""
            suffix = f" tới {recipient}" if recipient else ""
            return f"📧 Đã phát hành RFQ qua email{suffix} và ghi nhận phát hành vào hồ sơ."

        raise ValueError(f"unknown action {action_id}")

    async def _find_pending_approval(
        self, cp: str, case_id: UUID, context: AccessContext
    ) -> UUID | None:
        uow_factory = self.container.uow_factory
        if uow_factory is None:
            return None
        wanted_type = f"preparation.{cp}"
        async with uow_factory(context) as uow:
            for request in await uow.approvals.list_pending():
                if request.approval_type == wanted_type and str(
                    request.payload.get("case_id", "")
                ) == str(case_id):
                    return request.id
        return None

    # -------------------------------------------------------------- render ---
    async def _reveal_thinking(self, channel: str, thinking_ts: str, thinking: str) -> None:
        """Replace the placeholder with the model's visible reasoning."""
        if not thinking:
            await self.chat.chat_client.update_message(
                channel=channel, ts=thinking_ts, text="💭 (không có suy luận cho lượt này)"
            )
            return
        trimmed = thinking.strip()
        if len(trimmed) > _THINKING_MAX_CHARS:
            trimmed = trimmed[:_THINKING_MAX_CHARS].rstrip() + "\n… _(đã rút gọn)_"
        quoted = "\n".join(f">{line}" for line in trimmed.splitlines())
        await self.chat.chat_client.update_message(
            channel=channel,
            ts=thinking_ts,
            text="💭 Suy nghĩ của Digital Worker",
            blocks=[
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"💭 *Suy nghĩ*\n{quoted}"},
                }
            ],
        )

    async def _send_reply(self, channel: str, thread_ts: str | None, reply: Any) -> None:
        blocks: list[dict[str, Any]] | None = None
        if reply.kind == "confirm_card" and reply.conversation_id is not None:
            summary = "\n".join(reply.summary_lines)
            blocks = [
                {"type": "section", "text": {"type": "mrkdwn", "text": f"*{reply.text}*"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": summary}},
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "style": "primary",
                            "text": {"type": "plain_text", "text": "Tạo hồ sơ", "emoji": True},
                            "action_id": _CONFIRM_ACTION,
                            "value": str(reply.conversation_id),
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Sửa thông tin", "emoji": True},
                            "action_id": _EDIT_ACTION,
                            "value": str(reply.conversation_id),
                        },
                    ],
                },
            ]
        await self.chat.chat_client.post_message(
            channel=channel, thread_ts=thread_ts, text=reply.text, blocks=blocks
        )

    @staticmethod
    def _strip_mention(text: str) -> str:
        # "<@U123ABC> mua 100 laptop" → "mua 100 laptop"
        return re.sub(r"<@[A-Z0-9]+>", "", text).strip()


def start_slack_front_office(
    container: ApiContainer, chat: ChatFrontOffice, repo_root: Path
) -> asyncio.Task[None]:
    """Spawn the Socket Mode loop as a background task (cancelled on shutdown)."""
    from dw_connectors.adapters.slack_chat import SlackSocketModeRunner

    service = SlackFrontOfficeService(container=container, chat=chat, repo_root=repo_root)
    runner = SlackSocketModeRunner(app_token=chat.app_token, handler=service.handle_envelope)
    return asyncio.get_running_loop().create_task(runner.run_forever())
