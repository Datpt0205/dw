"""Zalo front office for DW01: chat intake + word-based approvals.

Long-polls the Zalo Bot Platform (Telegram-style dialect) — no public URL
needed. Same trust path as Slack/Telegram: zalo user id → demo subject via
configuration → DB membership builds the AccessContext (chat is never
authorization). NO buttons exist on this channel — everything runs on plain
Vietnamese:

- intake: chat như thường (ConversationIntakeService, channel-agnostic);
- confirm card → "đồng ý" tạo hồ sơ / "sửa ..." chỉnh lại;
- approvals → "duyệt cp1", "từ chối cp2", "xác minh", "lập addendum ..."
  (shared ``DecisionEngine`` — same handlers the Slack buttons call);
- case picker → "chọn 2".
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import yaml

from dw_api.channels.decisions import DecisionEngine
from dw_connectors.adapters.zalo_bot import ZaloBotClient
from dw_platform.application.access_context import AccessContext
from dw_platform.application.identity import VerifiedClaims

if TYPE_CHECKING:
    from dw_api.bootstrap import ApiContainer
    from dw_tender.application.conversation.service import (
        ChatReply,
        ConversationIntakeService,
        TurnOutcome,
    )

logger = logging.getLogger("dw_api.channels.zalo")

_CONFIRM_PHRASES = ("đồng ý", "dong y", "xác nhận", "xac nhan", "ok", "oke", "chốt", "chot")
_EDIT_PHRASES = ("sửa", "sua", "chỉnh", "chinh")
_PICK_RE = re.compile(r"^\s*chọn\s+(\d)\s*$", re.IGNORECASE)
_THINKING_MAX = 1200


def _with_reasoning(thinking: str, reply: str) -> str:
    """One message: the reasoning leads, the answer follows.

    Zalo has no rich text, so a separate "thinking" message just reads as a
    second reply. Keeping both in one bubble — reasoning in a light gutter,
    a hairline, then the answer — keeps the turn to a single notification and
    needs no label to explain itself.
    """
    lines = [ln.strip() for ln in thinking[:_THINKING_MAX].splitlines() if ln.strip()]
    if not lines:
        return reply
    body = "\n".join(f"┆ {ln.lstrip('•').strip()}" for ln in lines)
    return f"{body}\n┄┄┄┄┄┄┄┄┄┄\n{reply}"


@dataclass
class ZaloFrontOfficeService:
    container: ApiContainer
    conversation_service: ConversationIntakeService
    bot_token: str
    repo_root: Path
    web_base_url: str = "http://localhost:3000"
    # Visible thinking is produced and traced regardless; this only decides
    # whether the card is pushed to the chat (DW_ZALO_SHOW_THINKING).
    show_thinking: bool = False
    _client: ZaloBotClient = field(init=False)
    _offset: int = field(default=0, init=False)
    _engine: DecisionEngine | None = field(default=None, init=False)
    # chat_id → last case-picker options [(conversation_id, title), ...]
    _picker_options: dict[str, list[tuple[str, str]]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._client = ZaloBotClient(bot_token=self.bot_token)

    @property
    def engine(self) -> DecisionEngine:
        if self._engine is None:
            self._engine = DecisionEngine(
                container=self.container,
                conversation_service=self.conversation_service,
                channel_label="Zalo",
            )
        return self._engine

    # ---------------------------------------------------------------- loop --
    async def run_forever(self) -> None:
        logger.info("zalo front office polling started")
        backoff = 1.0
        while True:
            try:
                updates = await self._client.get_updates(self._offset)
                backoff = 1.0
                for update in updates:
                    self._offset = max(self._offset, int(update.get("update_id", 0)) + 1)
                    try:
                        await self._handle_update(update)
                    except Exception:  # one bad message must not kill the loop
                        logger.exception("zalo update failed")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("zalo poll error (%s); retry in %.0fs", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    # ------------------------------------------------------------ identity --
    def _resolve_subject(self, zalo_user_id: str) -> str | None:
        path = self.repo_root / "configs" / "demo" / "channel_identities.yaml"
        if path.exists():
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            mapping = raw.get("zalo") or {}
            if mapping.get(zalo_user_id):
                return str(mapping[zalo_user_id])
        return self.container.settings.zalo_user_reverse_map().get(zalo_user_id)

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
            VerifiedClaims(subject=subject, email=None, issuer="dw-zalo"),
            UUID(str(entry["tenant_id"])),
            UUID(str(entry["workspace_id"])),
        )
        return context, str(entry.get("display_name", subject))

    # ------------------------------------------------------------- handler --
    async def _handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message") or {}
        chat_id = str((message.get("chat") or {}).get("id", "") or "")
        from_id = str((message.get("from") or {}).get("id", "") or "")
        text = str(message.get("text") or "").strip()
        if not chat_id or not from_id or not text:
            return

        subject = self._resolve_subject(from_id)
        if subject is None:
            await self._client.send_message(
                chat_id,
                f"👋 Chào bạn! Zalo ID của bạn là {from_id} — chưa được gán với "
                "người dùng DW.\nNhờ quản trị viên thêm vào .env "
                "(ZALO_USER_*_ID) hoặc configs/demo/channel_identities.yaml "
                f'(mục zalo:)\n  "{from_id}": dev|an.nguyen',
            )
            return
        resolved = await self._access_context(subject)
        if resolved is None:
            logger.warning("zalo subject %s not in roster/membership", subject)
            return
        context, display_name = resolved
        channel_key = f"zalo:{chat_id}"

        # 1) Case picker in words: "chọn 2".
        pick = _PICK_RE.match(text)
        if pick and self._picker_options.get(chat_id):
            options = self._picker_options[chat_id]
            index = int(pick.group(1)) - 1
            if 0 <= index < len(options):
                outcome = await self.conversation_service.handle_pick_case(
                    conversation_id=UUID(options[index][0]), context=context
                )
                await self._send_outcome(chat_id, outcome)
                return

        active = await self.conversation_service.store.find_active(
            tenant_id=context.tenant_id,
            workspace_id=context.workspace_id,
            channel_key=channel_key,
        )
        lowered = text.casefold().strip(" .!")

        # 2) Confirm-before-commit in words (the confirm card has no buttons).
        if active is not None and active.state == "confirming":
            if any(lowered == p or lowered.startswith(p + " ") for p in _CONFIRM_PHRASES):
                outcome = await self.conversation_service.handle_action(
                    action="confirm",
                    conversation_id=active.id,
                    context=context,
                    display_name=display_name,
                )
                await self._send_outcome(chat_id, outcome)
                return
            if lowered in _EDIT_PHRASES:
                outcome = await self.conversation_service.handle_action(
                    action="edit",
                    conversation_id=active.id,
                    context=context,
                    display_name=display_name,
                )
                await self._send_outcome(chat_id, outcome)
                return

        # 3) Decisions in words ("duyệt cp1", "xác minh", "lập addendum …") —
        #    only when no intake is mid-flight in this chat (mirrors Slack).
        if active is None:
            decision_reply = await self.engine.try_text(text, context, display_name)
            if decision_reply is not None:
                await self._client.send_message(chat_id, decision_reply)
                return

        # 4) Normal conversational turn. Native typing indicator ("đang
        # nhập…") pulses while the model works and clears itself when the
        # answer lands — no placeholder message left in the history.
        typing = asyncio.get_running_loop().create_task(self._typing_loop(chat_id))
        try:
            outcome = await self.conversation_service.handle_message(
                channel_key=channel_key,
                text=text,
                context=context,
                display_name=display_name,
            )
        except Exception:
            typing.cancel()
            await self._client.send_message(
                chat_id, "⚠️ Xin lỗi, tôi gặp trục trặc khi xử lý — bạn nhắn lại giúp nhé."
            )
            raise
        finally:
            typing.cancel()
        await self._send_outcome(chat_id, outcome)

    async def _typing_loop(self, chat_id: str) -> None:
        """Re-emit the typing action every few seconds (it fades after ~5s)."""
        while True:
            try:
                await self._client.send_chat_action(chat_id, "typing")
            except Exception:  # cosmetic only — never break the turn
                return
            await asyncio.sleep(4)

    # ------------------------------------------------------------ rendering --
    async def _send_outcome(self, chat_id: str, outcome: TurnOutcome) -> None:
        for index, reply in enumerate(outcome.replies):
            text = self._render_reply(chat_id, reply)
            # Reasoning rides along with the FIRST reply of the turn, never as
            # a message of its own.
            if index == 0 and outcome.thinking and self.show_thinking:
                text = _with_reasoning(outcome.thinking, text)
            await self._client.send_message(chat_id, text)

    def _render_reply(self, chat_id: str, reply: ChatReply) -> str:
        parts = [reply.text]
        if reply.summary_lines:
            parts.append("")
            parts.extend(f"• {line}" for line in reply.summary_lines)
        if reply.kind == "confirm_card":
            parts.append("")
            parts.append("👉 Nhắn «đồng ý» để tạo hồ sơ, hoặc nhắn nội dung muốn sửa.")
        if reply.kind == "case_link" and reply.case_id:
            parts.append(f"🔗 {self.web_base_url}/procurement/dw01/cases/{reply.case_id}")
        if reply.case_options:
            self._picker_options[chat_id] = [(cid, title) for cid, title in reply.case_options]
            parts.append("")
            for i, (_cid, title) in enumerate(reply.case_options, start=1):
                parts.append(f"  {i}. {title}")
            parts.append("👉 Đổi hồ sơ: nhắn «chọn 1», «chọn 2»…")
        return "\n".join(parts)


def start_zalo_front_office(container: ApiContainer, repo_root: Path) -> asyncio.Task[None] | None:
    """Spawn the polling loop when a bot token + conversation service exist."""
    token = container.settings.zalo_bot_token
    if not token or container.conversation_service is None:
        return None
    service = ZaloFrontOfficeService(
        container=container,
        conversation_service=container.conversation_service,
        bot_token=token,
        repo_root=repo_root,
        web_base_url=container.settings.public_web_url,
        show_thinking=container.settings.zalo_show_thinking,
    )
    return asyncio.get_running_loop().create_task(service.run_forever(), name="dw-zalo")
