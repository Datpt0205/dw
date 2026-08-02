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
from dataclasses import dataclass, field
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
_PICK_CASE_ACTION = "dw01_chat_pick"
# P4: decision/publication buttons on worker-sent cards.
_INTAKE_APPROVE = "dw01_intake_approve"
_INTAKE_REJECT = "dw01_intake_reject"
_CP_APPROVE = "dw01_cp_approve"
_CP_REJECT = "dw01_cp_reject"
_CP4_CONFIRM = "dw01_cp4_confirm"
_PUBLISH = "dw01_publish"
_VIEW_PR = "dw01_view_pr"
# Receipt desk (bước 8): procurement records incoming bids with one click.
_RECORD_SUB = "dw01_record_sub"
_OPEN_BIDS = "dw01_open_bids"

# Slack section blocks cap at 3000 chars; keep the thinking readable.
_THINKING_MAX_CHARS = 2200


@dataclass
class SlackFrontOfficeService:
    """Handles Socket Mode envelopes end to end."""

    container: ApiContainer
    chat: ChatFrontOffice
    repo_root: Path
    # Receipt desk: channel → {case_id, supplier, card_ts} while waiting for
    # the actual bid file to be dropped into the DM (in-memory is fine for the
    # demo — a restart just means clicking the supplier button again).
    pending_uploads: dict[str, dict[str, str]] = field(default_factory=dict)

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
        if event.get("type") == "app_home_opened":
            await self._publish_home(str(event.get("user", "")))
            return
        if event.get("type") not in ("message", "app_mention"):
            return
        if event.get("subtype") == "file_share" and not event.get("bot_id"):
            # Receipt desk: the actual bid document dropped into the DM.
            # Dedupe first — a Slack redelivery must not double-record a bid.
            file_event_id = str(payload.get("event_id") or "")
            if file_event_id and not await self.chat.conversation_store.claim_event(
                f"slack:{file_event_id}"
            ):
                return
            await self._handle_receipt_file(event)
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

        # Free-text receipt desk: "Synnex FPT nộp file bên dưới" arms the
        # file wait exactly like clicking the supplier button (deterministic
        # name match). Skipped while an intake chat is mid-flight here.
        active_conv = await self.chat.conversation_store.find_active(
            tenant_id=context.tenant_id,
            workspace_id=context.workspace_id,
            channel_key=channel_key,
        )
        if active_conv is None and await self._arm_receipt_from_text(
            channel, self._strip_mention(text), context
        ):
            return

        # Thinking-first UX: post a placeholder immediately (the reasoner can
        # take a while), then replace it with the model's visible reasoning
        # BEFORE the actual replies arrive as separate messages.
        thinking_ts = await self.chat.chat_client.post_message(
            channel=channel, thread_ts=thread_ts, text="Đang suy nghĩ…"
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
        # Buttons repeated in one block carry an index suffix (Slack demands
        # unique action_ids) — dispatch on the prefix.
        action_id = action_id.split(":", 1)[0]
        known = (
            _CONFIRM_ACTION,
            _EDIT_ACTION,
            _PICK_CASE_ACTION,
            _INTAKE_APPROVE,
            _INTAKE_REJECT,
            _CP_APPROVE,
            _CP_REJECT,
            _CP4_CONFIRM,
            _PUBLISH,
            _VIEW_PR,
            _RECORD_SUB,
            _OPEN_BIDS,
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

        if action_id == _VIEW_PR:
            await self._post_pr_preview(value, channel, context)
            return
        if action_id in (
            _INTAKE_APPROVE,
            _INTAKE_REJECT,
            _CP_APPROVE,
            _CP_REJECT,
            _CP4_CONFIRM,
            _PUBLISH,
            _RECORD_SUB,
            _OPEN_BIDS,
        ):
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
        if action_id == _PICK_CASE_ACTION:
            picked = await self.chat.conversation_service.handle_pick_case(
                conversation_id=conv_uuid, context=context
            )
            for reply in picked.replies:
                await self._send_reply(channel, message.get("thread_ts"), reply)
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

    # --------------------------------------------------------- app home (P7) --
    async def _publish_home(self, slack_user_id: str) -> None:
        """P7: the "Việc của tôi" tab — pending items first, then running cases."""
        subject = self._resolve_subject(slack_user_id)
        if subject is None:
            return
        resolved = await self._access_context(subject)
        if resolved is None or self.container.preparation is None:
            return
        context, display_name = resolved
        cases = await self.container.preparation.list_cases.handle(context)

        labels = {
            "draft": "Chờ xác minh đầu vào",
            "waiting_clarification": "Chờ làm rõ",
            "cp1_pending": "Chờ duyệt CP1",
            "cp2_pending": "Chờ duyệt CP2",
            "cp3_pending": "Chờ duyệt CP3 (addendum)",
            "receiving_bids": "Đang nhận hồ sơ dự thầu",
            "package_official": "Hồ sơ chính thức — chờ phát hành",
            "published": "Đã phát hành",
            "completed": "Hoàn tất",
        }
        decide_states = {"draft", "cp1_pending", "cp2_pending", "cp3_pending", "receiving_bids"}
        can_decide = context.has_scope("approvals.decide")

        pending, running = [], []
        for case in cases:
            state = str(case.state)
            line = (
                f"• *{case.title}* — {labels.get(state, state)}\n"
                f"  <{self.chat.conversation_service.web_base_url}/procurement/dw01/cases/"
                f"{case.id}|Mở hồ sơ>"
            )
            if can_decide and state in decide_states:
                pending.append(line)
            elif state not in ("completed", "intake_rejected"):
                running.append(line)

        blocks: list[dict[str, Any]] = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"Việc của {display_name}", "emoji": True},
            }
        ]
        if pending:
            blocks += [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*⏳ Chờ quyết định của bạn*\n" + "\n".join(pending[:10]),
                    },
                }
            ]
        if running:
            blocks += [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*📁 Hồ sơ đang chạy*\n" + "\n".join(running[:10]),
                    },
                }
            ]
        if not pending and not running:
            blocks += [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "Không có việc nào đang chờ. Nhắn tin cho tôi khi cần mua sắm nhé!",
                    },
                }
            ]
        blocks += [
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "Cập nhật mỗi lần bạn mở tab này — quyết định qua thẻ trong DM.",
                    }
                ],
            }
        ]
        await self.chat.chat_client.publish_home_view(user_id=slack_user_id, blocks=blocks)

    async def _post_pr_preview(self, value: str, channel: str, context: AccessContext) -> None:
        """[📄 Xem PR]: post the source PR inline so the approver never leaves
        Slack. Authorized via the clicker's real context (tender.read + RLS)."""
        preparation = self.container.preparation
        if preparation is None:
            return
        try:
            view = await preparation.get_case.handle(UUID(value), context)
        except Exception as exc:
            await self.chat.chat_client.post_message(
                channel=channel, text=f"⚠️ Không mở được PR: {str(exc)[:200]}"
            )
            return
        pr_doc = next(
            (doc for doc in view.documents if doc.kind == "approved_pr" and doc.text_content),
            None,
        )
        if pr_doc is None:
            await self.chat.chat_client.post_message(
                channel=channel,
                text="Không tìm thấy nội dung PR dạng văn bản — mở hồ sơ trên web để xem.",
            )
            return
        body = pr_doc.text_content or ""
        if len(body) > 2800:
            body = body[:2800].rstrip() + "\n… (rút gọn — xem đầy đủ trên web)"
        await self.chat.chat_client.post_message(
            channel=channel,
            text=f"📄 PR — {view.title}",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*📄 {pr_doc.title or pr_doc.filename}* — {view.title}",
                    },
                },
                {"type": "section", "text": {"type": "mrkdwn", "text": f"```{body}```"}},
            ],
        )

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
        # Receipt desk: a supplier click does NOT record yet — it arms the
        # channel to expect the actual bid FILE, and re-renders the card.
        if action_id == _RECORD_SUB:
            try:
                await self._start_receipt_upload(channel, message, value, context)
            except Exception as exc:
                logger.warning("receipt upload arm failed: %s", exc)
                await self.chat.chat_client.post_message(
                    channel=channel, text=f"⚠️ Không thực hiện được: {str(exc)[:200]}"
                )
            return
        try:
            reply = await self._execute_decision(action_id, value, context, display_name)
        except Exception as exc:
            logger.warning("slack decision failed action=%s: %s", action_id, exc)
            reply = f"⚠️ Không thực hiện được: {str(exc)[:300]}"
        # Replace the card with the outcome in-place (one message, no
        # "đã ghi nhận thao tác" clutter); fall back to a new message.
        # A failed close (⚠️) must PRESERVE the receipt card and its buttons.
        preserve_card = action_id == _OPEN_BIDS and reply.startswith("⚠️")
        if message.get("ts") and not preserve_card:
            await self.chat.chat_client.update_message(
                channel=channel, ts=str(message["ts"]), text=reply
            )
        else:
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
            if not approve:
                return f"⛔ Đã từ chối {label} — quy trình dừng, người tạo sẽ được thông báo."
            if cp == "cp2":
                # CP2 per B5.4 IS the publication authorization ("cho phép
                # phát hành") — publish immediately, no extra human click.
                # decide() resumed the graph synchronously, so the official
                # package is already sealed at this point.
                try:
                    result = await preparation.auto_publish.handle(case_id, context)
                    sent_to = str(result.get("sent_to", "")) if isinstance(result, dict) else ""
                    suffix = f" tới {sent_to}" if sent_to else ""
                    return (
                        "✅ Đã duyệt CP2 — bộ hồ sơ niêm phong bản chính thức "
                        f"và RFQ đã phát hành qua email{suffix}."
                    )
                except Exception as exc:
                    logger.warning("auto publish after CP2 failed: %s", exc)
                    return (
                        "✅ Đã duyệt CP2 — hồ sơ đã niêm phong, nhưng phát hành "
                        f"tự động chưa chạy được ({str(exc)[:160]}). "
                        "Người tạo có thể yêu cầu phát hành lại qua chat."
                    )
            if cp == "cp1":
                return (
                    "✅ Đã duyệt CP1 — mình đang soạn hồ sơ mời thầu và tiêu chí, "
                    "sẽ trình CP2 trong ít phút."
                )
            return f"✅ Đã duyệt {label} — quy trình tiếp tục chạy tự động."

        if action_id == _CP4_CONFIRM:
            from dw_tender.application.preparation.handlers import CompleteCp4Command

            case_id = UUID(value)
            # Biên bản do hệ thống lập từ hồ sơ (danh mục HSDT nằm trong sổ
            # tiếp nhận đã niêm phong) — không ai phải upload file.
            minutes_md = (
                f"# Biên bản mở thầu\n\n"
                f"- Thời điểm mở: {now:%d/%m/%Y %H:%M} (UTC)\n"
                f"- Người xác nhận: {display_name} (qua Slack)\n"
                f"- Danh mục hồ sơ dự thầu: theo sổ tiếp nhận (SUBMISSION_REGISTER) "
                f"đã niêm phong trong hồ sơ.\n"
                f"- Ghi chú: biên bản do hệ thống lập tự động trong môi trường mô phỏng.\n"
            )
            await preparation.complete_cp4.handle(
                case_id,
                CompleteCp4Command(
                    filename="bid-opening-minutes.md",
                    content_type="text/markdown; charset=utf-8",
                    content=minutes_md.encode("utf-8"),
                    opening_at=now.isoformat(),
                    witnesses=(display_name,),
                    approval_reference=f"SLACK-{now:%Y%m%d-%H%M%S}",
                    comment=f"Xác nhận CP4 qua Slack bởi {display_name}",
                ),
                context,
            )
            return (
                "CP4 hoàn tất — biên bản mở thầu đã lập, gói bàn giao DW02 đã "
                "niêm phong. Quy trình DW01 kết thúc."
            )

        if action_id == _OPEN_BIDS:
            from dw_kernel.errors import ConflictError, DomainError

            case_id = UUID(value)
            try:
                count = await preparation.request_cp4.handle(case_id, context)
            except (ConflictError, DomainError):
                return (
                    "⚠️ Chưa có hồ sơ dự thầu nào được ghi nhận — bấm ghi nhận "
                    "từng nhà cung cấp trước rồi mới chốt sổ nhé."
                )
            return (
                f"Đã chốt sổ với {count} hồ sơ dự thầu — thẻ xác nhận mở thầu (CP4) "
                "sẽ đến ngay sau đây."
            )

        if action_id == _PUBLISH:
            case_id = UUID(value)
            result = await preparation.auto_publish.handle(case_id, context)
            recipient = str(result.get("recipient", "")) if isinstance(result, dict) else ""
            suffix = f" tới {recipient}" if recipient else ""
            return f"Đã phát hành RFQ qua email{suffix} và ghi nhận phát hành vào hồ sơ."

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

    # ------------------------------------------------------- receipt desk ---
    async def _receipt_state(
        self, case_id: UUID, context: AccessContext
    ) -> tuple[str, list[str], set[str]]:
        """(case_title, invited suppliers, suppliers already recorded)."""
        preparation = self.container.preparation
        assert preparation is not None
        view = await preparation.get_case.handle(case_id, context)
        latest: dict[str, Any] = {}
        for artifact in view.artifacts:
            current = latest.get(artifact.artifact_type)
            if current is None or artifact.artifact_version > current.artifact_version:
                latest[artifact.artifact_type] = artifact
        suppliers: list[str] = []
        supplier_input = latest.get("supplier_input")
        if supplier_input is not None:
            suppliers = [
                str(s.get("name", "")).strip()
                for s in supplier_input.content.get("suppliers", [])
                if isinstance(s, dict) and str(s.get("name", "")).strip()
            ]
        recorded: set[str] = set()
        register = latest.get("submission_register")
        if register is not None:
            recorded = {
                str(item.get("supplier_name", "")).strip()
                for item in register.content.get("items", [])
                if isinstance(item, dict)
            }
        return view.title, suppliers, recorded

    def _receipt_desk_blocks(
        self,
        *,
        case_id: UUID,
        title: str,
        suppliers: list[str],
        recorded: set[str],
        pending: str | None,
    ) -> list[dict[str, Any]]:
        """Server-rendered card state — Slack has no disabled buttons, so the
        'Chốt sổ' button simply does not exist until ≥1 bid is recorded."""
        lines: list[str] = []
        for name in suppliers:
            if name in recorded:
                lines.append(f"✅ {name} — đã nhận hồ sơ.")
            elif name == pending:
                lines.append(f"⏳ {name} — đang chờ file HSDT, thả file vào DM này.")
        body = f"*{title}*" + "".join(f"\n{line}" for line in lines)
        buttons: list[dict[str, Any]] = []
        for i, name in enumerate(suppliers):
            if name in recorded or name == pending:
                continue
            buttons.append(
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": f"{name} đã nộp", "emoji": True},
                    "action_id": f"{_RECORD_SUB}:{i}",
                    "value": f"{case_id}|{name}",
                }
            )
        if recorded:
            buttons.append(
                {
                    "type": "button",
                    "style": "primary",
                    "text": {
                        "type": "plain_text",
                        "text": "Chốt sổ & mở thầu",
                        "emoji": True,
                    },
                    "action_id": _OPEN_BIDS,
                    "value": str(case_id),
                }
            )
        context_text = (
            f"Đã nhận {len(recorded)}/{len(suppliers)} hồ sơ."
            if recorded
            else "Nút Chốt sổ & mở thầu sẽ hiện khi có ít nhất 1 hồ sơ được ghi nhận."
        )
        blocks: list[dict[str, Any]] = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Tiếp nhận hồ sơ dự thầu*"},
            },
            {"type": "section", "text": {"type": "mrkdwn", "text": body}},
        ]
        if buttons:
            blocks.append({"type": "actions", "elements": buttons})
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": context_text}]})
        return blocks

    async def _repost_receipt_card(
        self,
        channel: str,
        old_ts: str,
        case_id: UUID,
        context: AccessContext,
        pending: str | None,
    ) -> str:
        """Move the receipt card to the BOTTOM of the DM (delete + repost).

        Updating in place strands the buttons above newer messages — the next
        action must always be the last thing on screen.
        """
        title, suppliers, recorded = await self._receipt_state(case_id, context)
        if old_ts:
            await self.chat.chat_client.delete_message(channel=channel, ts=old_ts)
        return await self.chat.chat_client.post_message(
            channel=channel,
            text=f"Tiếp nhận hồ sơ dự thầu — {title}",
            blocks=self._receipt_desk_blocks(
                case_id=case_id,
                title=title,
                suppliers=suppliers,
                recorded=recorded,
                pending=pending,
            ),
        )

    async def _start_receipt_upload(
        self,
        channel: str,
        message: dict[str, Any],
        value: str,
        context: AccessContext,
    ) -> None:
        case_raw, _, supplier = value.partition("|")
        case_id = UUID(case_raw)
        supplier = supplier.strip() or "Nhà cung cấp"
        await self.chat.chat_client.post_message(
            channel=channel,
            text=(
                f"Thả file hồ sơ dự thầu của {supplier} vào đây (PDF/DOCX/ZIP…) — "
                "mình lưu làm hồ sơ chính thức và lập biên nhận."
            ),
        )
        # Card moves to the bottom so the next action is always on screen.
        new_ts = await self._repost_receipt_card(
            channel, str(message.get("ts", "")), case_id, context, supplier
        )
        self.pending_uploads[channel] = {
            "case_id": str(case_id),
            "supplier": supplier,
            "card_ts": new_ts,
        }

    async def _match_receipt_supplier(
        self, text: str, context: AccessContext, *, require_keyword: bool
    ) -> tuple[UUID, str] | None:
        """Free-text receipt: match an INVITED supplier of a case that is
        receiving bids. Deterministic on purpose — the invited list is known,
        so name containment beats an LLM here (no hallucination, no latency).
        """
        preparation = self.container.preparation
        if preparation is None or not text.strip():
            return None
        lowered = text.casefold()
        if require_keyword and not any(
            k in lowered for k in ("nộp", "gửi", "nop", "gui", "submit")
        ):
            return None
        cases = await preparation.list_cases.handle(context)
        matches: list[tuple[UUID, str]] = []
        for case in cases:
            if case.state not in ("published", "receiving_bids"):
                continue
            _, suppliers, recorded = await self._receipt_state(case.id, context)
            for name in suppliers:
                if name in recorded:
                    continue
                n = name.casefold()
                first = n.split()[0] if n.split() else n
                if n in lowered or (len(first) >= 4 and first in lowered):
                    matches.append((case.id, name))
        # Exactly one unambiguous match, or nothing (a multi-name message is
        # most likely an intake sentence, not a receipt).
        return matches[0] if len(matches) == 1 else None

    async def _arm_receipt_from_text(self, channel: str, text: str, context: AccessContext) -> bool:
        """'Synnex FPT nộp file bên dưới' behaves like clicking the button."""
        match = await self._match_receipt_supplier(text, context, require_keyword=True)
        if match is None:
            return False
        case_id, supplier = match
        old_ts = self.pending_uploads.get(channel, {}).get("card_ts", "")
        await self.chat.chat_client.post_message(
            channel=channel,
            text=(
                f"OK — thả file hồ sơ dự thầu của {supplier} vào đây, "
                "mình lưu bản chính thức và lập biên nhận."
            ),
        )
        new_ts = await self._repost_receipt_card(channel, old_ts, case_id, context, supplier)
        self.pending_uploads[channel] = {
            "case_id": str(case_id),
            "supplier": supplier,
            "card_ts": new_ts,
        }
        return True

    async def _handle_receipt_file(self, event: dict[str, Any]) -> None:
        channel = str(event.get("channel", ""))
        user = str(event.get("user", ""))
        subject = self._resolve_subject(user)
        resolved = await self._access_context(subject) if subject else None
        if resolved is None:
            return
        context, display_name = resolved
        pending = self.pending_uploads.get(channel)
        if pending is None:
            # No armed supplier — try the file's caption ("Synnex FPT" typed
            # alongside the drop records it in one step, no keyword needed).
            caption = str(event.get("text", "") or "")
            match = await self._match_receipt_supplier(caption, context, require_keyword=False)
            if match is None:
                return  # unrelated file share
            pending = {
                "case_id": str(match[0]),
                "supplier": match[1],
                "card_ts": "",
            }
        files = event.get("files") or []
        if not files:
            return
        info = files[0]
        size = int(info.get("size", 0) or 0)
        if size > 10 * 1024 * 1024:
            await self.chat.chat_client.post_message(
                channel=channel, text="⚠️ File vượt 10MB — gửi bản nhỏ hơn giúp mình nhé."
            )
            return
        url = str(info.get("url_private_download") or info.get("url_private") or "")
        filename = str(info.get("name") or "ho-so-du-thau.bin")
        content_type = str(info.get("mimetype") or "application/octet-stream")
        try:
            content = await self.chat.chat_client.download_file(url)
        except Exception as exc:
            logger.warning("bid file download failed: %s", exc)
            await self.chat.chat_client.post_message(
                channel=channel,
                text=(
                    "⚠️ Mình chưa tải được file từ Slack — kiểm tra app đã có "
                    "scope `files:read` và Reinstall chưa nhé."
                ),
            )
            return
        from dw_kernel.errors import ConflictError, DomainError
        from dw_tender.application.preparation.handlers import RecordSubmissionCommand

        preparation = self.container.preparation
        assert preparation is not None
        case_id = UUID(pending["case_id"])
        supplier = pending["supplier"]
        now = datetime.now(tz=UTC)
        try:
            await preparation.record_submission.handle(
                case_id,
                RecordSubmissionCommand(
                    filename=filename,
                    content_type=content_type,
                    content=content,
                    supplier_name=supplier,
                    received_at=now.isoformat(),
                    receipt_status="on_time",
                    external_reference=f"slack-file:{info.get('id', '')}",
                ),
                context,
            )
        except (ConflictError, DomainError) as exc:
            await self.chat.chat_client.post_message(
                channel=channel, text=f"⚠️ Không ghi nhận được: {str(exc)[:200]}"
            )
            return
        self.pending_uploads.pop(channel, None)
        await self.chat.chat_client.post_message(
            channel=channel,
            text=(
                f"Đã nhận hồ sơ dự thầu của {supplier} — {filename} "
                f"({size // 1024} KB), {display_name} ghi nhận, biên nhận lưu vào hồ sơ."
            ),
        )
        # Fresh card at the bottom: ✓ line for this supplier + (now) the close button.
        await self._repost_receipt_card(channel, pending.get("card_ts", ""), case_id, context, None)

    # -------------------------------------------------------------- render ---
    async def _reveal_thinking(self, channel: str, thinking_ts: str, thinking: str) -> None:
        """Replace the placeholder with the model's visible reasoning."""
        if not thinking:
            await self.chat.chat_client.update_message(
                channel=channel, ts=thinking_ts, text="(không có suy luận cho lượt này)"
            )
            return
        trimmed = thinking.strip()
        if len(trimmed) > _THINKING_MAX_CHARS:
            trimmed = trimmed[:_THINKING_MAX_CHARS].rstrip() + "\n… _(đã rút gọn)_"
        # Inline, de-emphasized: a context block renders as small grey text —
        # visibly "the worker's reasoning" without shouting over the reply.
        await self.chat.chat_client.update_message(
            channel=channel,
            ts=thinking_ts,
            text="Suy nghĩ",
            blocks=[
                {
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": f"_Suy nghĩ_\n{trimmed}"}],
                }
            ],
        )

    async def _send_reply(self, channel: str, thread_ts: str | None, reply: Any) -> None:
        blocks: list[dict[str, Any]] | None = None
        if getattr(reply, "case_options", ()):
            blocks = [
                {"type": "section", "text": {"type": "mrkdwn", "text": reply.text}},
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": title[:70], "emoji": True},
                            "action_id": _PICK_CASE_ACTION,
                            "value": conv_id,
                        }
                        for conv_id, title in reply.case_options
                    ],
                },
            ]
        elif reply.kind == "confirm_card" and reply.conversation_id is not None:
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


def build_front_office(
    container: ApiContainer, chat: ChatFrontOffice, repo_root: Path
) -> SlackFrontOfficeService:
    return SlackFrontOfficeService(container=container, chat=chat, repo_root=repo_root)


def start_slack_front_office(
    container: ApiContainer,
    chat: ChatFrontOffice,
    repo_root: Path,
    service: SlackFrontOfficeService | None = None,
) -> asyncio.Task[None]:
    """Spawn the Socket Mode loop as a background task (cancelled on shutdown)."""
    from dw_connectors.adapters.slack_chat import SlackSocketModeRunner

    service = service or build_front_office(container, chat, repo_root)
    runner = SlackSocketModeRunner(app_token=chat.app_token, handler=service.handle_envelope)
    return asyncio.get_running_loop().create_task(runner.run_forever())
