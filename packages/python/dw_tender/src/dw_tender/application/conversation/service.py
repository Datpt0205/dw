"""Channel-agnostic conversation service for DW01 chat intake.

Depends only on ports (store, model gateway, application handlers) — the Slack
adapter renders replies; this service never sees Slack payloads. Flow per plan:
slot-filling → deterministic completeness → confirm-before-commit → the same
``CreatePreparationCaseCommand`` the web UI uses.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC
from typing import Literal, Protocol

from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.ports import ModelGateway, ModelRequest
from dw_kernel.ports import IdGenerator, UtcClock
from dw_platform.application.access_context import AccessContext
from dw_tender.application.conversation.schemas import (
    IntakeChatTurn,
    IntakeSlots,
    missing_required,
    render_pr_markdown,
)
from dw_tender.application.preparation.handlers import (
    CreatePreparationCaseCommand,
    CreatePreparationCaseHandler,
)
from dw_tender.application.preparation.rules import ProcurementRules
from dw_tender.domain.preparation.entities import BusinessDomain, ProcurementType

ConversationState = Literal["collecting", "confirming", "case_created", "cancelled"]


@dataclass(frozen=True, slots=True)
class ConversationView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    workspace_id: uuid.UUID
    channel_key: str
    subject: str
    state: str
    slots: IntakeSlots
    case_id: uuid.UUID | None


class ConversationStorePort(Protocol):
    """Durable conversation state (thread ↔ slots ↔ case)."""

    async def claim_event(self, event_id: str) -> bool:
        """True when this event is new; False on redelivery (skip processing)."""
        ...

    async def find_active(
        self, *, tenant_id: uuid.UUID, workspace_id: uuid.UUID, channel_key: str
    ) -> ConversationView | None: ...

    async def get(
        self, *, conversation_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> ConversationView | None: ...

    async def create(
        self,
        *,
        conversation_id: uuid.UUID,
        tenant_id: uuid.UUID,
        workspace_id: uuid.UUID,
        channel_key: str,
        subject: str,
    ) -> ConversationView: ...

    async def update(
        self,
        *,
        conversation_id: uuid.UUID,
        tenant_id: uuid.UUID,
        state: str | None = None,
        slots: IntakeSlots | None = None,
        case_id: uuid.UUID | None = None,
    ) -> None: ...


ReplyKind = Literal["message", "confirm_card", "case_link"]


@dataclass(frozen=True, slots=True)
class ChatReply:
    """Channel-neutral outbound message; the channel adapter renders it."""

    text: str
    kind: ReplyKind = "message"
    summary_lines: tuple[str, ...] = ()
    conversation_id: uuid.UUID | None = None
    case_id: uuid.UUID | None = None
    reasoning: str = ""


def _fmt_vnd(value: int | None) -> str:
    return f"{value:,}".replace(",", ".") + " VND" if value else "—"


@dataclass
class ConversationIntakeService:
    store: ConversationStorePort
    gateway: ModelGateway
    create_case: CreatePreparationCaseHandler
    rules: ProcurementRules
    clock: UtcClock
    id_generator: IdGenerator
    model_profile: str = "balanced"
    web_base_url: str = "http://localhost:3000"
    prompt_version: str = "1.0.0"
    worker_id: str = "dw01.chat_intake"
    worker_version: str = "1.0.0"

    # ------------------------------------------------------------- messages --
    async def handle_message(
        self,
        *,
        channel_key: str,
        text: str,
        context: AccessContext,
        display_name: str,
    ) -> list[ChatReply]:
        conversation = await self.store.find_active(
            tenant_id=context.tenant_id,
            workspace_id=context.workspace_id,
            channel_key=channel_key,
        )
        if conversation is None:
            conversation = await self.store.create(
                conversation_id=self.id_generator.new_uuid(),
                tenant_id=context.tenant_id,
                workspace_id=context.workspace_id,
                channel_key=channel_key,
                subject=str(context.principal_id),
            )

        turn = await self._run_turn(conversation, text, context, display_name)
        merged = conversation.slots.merged_with(turn.slots)

        if turn.intent == "cancel":
            await self.store.update(
                conversation_id=conversation.id,
                tenant_id=context.tenant_id,
                state="cancelled",
            )
            return [
                ChatReply(
                    text="Đã huỷ yêu cầu hiện tại. Khi cần mua sắm, bạn cứ nhắn cho tôi nhé."
                )
            ]

        missing = missing_required(merged, self.rules)
        next_state: ConversationState = "collecting" if missing else "confirming"
        await self.store.update(
            conversation_id=conversation.id,
            tenant_id=context.tenant_id,
            state=next_state,
            slots=merged,
        )

        if missing:
            return [ChatReply(text=turn.reply_vi, reasoning=turn.reasoning_summary)]
        return [self._confirm_card(conversation.id, merged, turn.reasoning_summary)]

    # -------------------------------------------------------------- actions --
    async def handle_action(
        self,
        *,
        action: Literal["confirm", "edit"],
        conversation_id: uuid.UUID,
        context: AccessContext,
        display_name: str,
    ) -> list[ChatReply]:
        conversation = await self.store.get(
            conversation_id=conversation_id, tenant_id=context.tenant_id
        )
        if conversation is None:
            return [ChatReply(text="Không tìm thấy phiên trao đổi này (có thể đã hết hạn).")]
        # Stale/double click: once the case exists, just repeat the link.
        if conversation.state == "case_created" and conversation.case_id:
            return [self._case_link(conversation.case_id, "Hồ sơ đã được tạo trước đó.")]
        if conversation.state != "confirming":
            return [
                ChatReply(text="Phiên này chưa ở bước xác nhận — bạn bổ sung thông tin đã nhé.")
            ]

        if action == "edit":
            await self.store.update(
                conversation_id=conversation.id,
                tenant_id=context.tenant_id,
                state="collecting",
            )
            return [
                ChatReply(
                    text=(
                        "OK, bạn nhắn phần muốn sửa (vd: «ngân sách 1,5 tỷ» hoặc "
                        "«thêm NCC FPT») — tôi sẽ cập nhật rồi xác nhận lại."
                    )
                )
            ]

        slots = conversation.slots
        pr_ref = f"SLACK-{self.clock.now().astimezone(UTC):%Y%m%d}-{str(conversation.id)[:8]}"
        command = CreatePreparationCaseCommand(
            title=slots.title or f"Mua {slots.item_summary or 'hàng hoá'}",
            description=slots.purpose or (slots.item_summary or ""),
            source_pr_ref=pr_ref,
            estimated_value_minor=slots.estimated_value_vnd or 0,
            currency="VND",
            deadline=f"{slots.deadline_days} ngày" if slots.deadline_days else None,
            owner_name=display_name,
            procurement_type=ProcurementType.GOODS,
            business_domain=BusinessDomain.GENERAL,
            pr_text=render_pr_markdown(slots, requester=display_name, pr_ref=pr_ref),
            pr_filename="slack-intake.md",
            pr_content_type="text/markdown; charset=utf-8",
            supplier_names=tuple(slots.supplier_names),
        )
        case_id = await self.create_case.handle(command, context)
        await self.store.update(
            conversation_id=conversation.id,
            tenant_id=context.tenant_id,
            state="case_created",
            case_id=case_id,
        )
        return [
            self._case_link(
                case_id,
                "✅ Đã tạo hồ sơ mua sắm từ trao đổi này. "
                "Quản lý sẽ nhận thông báo Slack để xác minh; sau khi xác minh, "
                "Digital Worker tự chạy và tôi sẽ báo bạn tiến độ.",
            )
        ]

    # ------------------------------------------------------------ internals --
    async def _run_turn(
        self,
        conversation: ConversationView,
        text: str,
        context: AccessContext,
        display_name: str,
    ) -> IntakeChatTurn:
        missing = missing_required(conversation.slots, self.rules)
        request = ModelRequest(
            task="conversation.intake_chat",
            prompt_id="conversation.intake_chat",
            prompt_version=self.prompt_version,
            variables={
                "known_slots": conversation.slots.model_dump_json(exclude_none=True),
                "missing_fields": "; ".join(missing) or "(không còn)",
                "message": text,
                "display_name": display_name,
                "today": f"{self.clock.now().astimezone(UTC):%d/%m/%Y}",
            },
            model_profile=self.model_profile,
        )
        run_context = RunContext(
            run_id=self.id_generator.new_uuid(),
            tenant_id=context.tenant_id,
            workspace_id=context.workspace_id,
            actor_id=context.principal_id,
            worker_id=self.worker_id,
            worker_version=self.worker_version,
            channel="slack",
            plan_id=context.plan_id,
            roles=context.roles,
            scopes=context.scopes,
            trace_id=f"chat-{str(conversation.id)[:12]}",
        )
        return await self.gateway.generate_structured(
            request, IntakeChatTurn, run_context=run_context
        )

    def _confirm_card(
        self, conversation_id: uuid.UUID, slots: IntakeSlots, reasoning: str
    ) -> ChatReply:
        method = (
            self.rules.select_method(slots.estimated_value_vnd)
            if slots.estimated_value_vnd
            else None
        )
        lines = [
            f"• Hàng hoá/dịch vụ: {slots.item_summary or slots.title or '—'}",
            f"• Số lượng: {slots.quantity or '—'}",
            f"• Ngân sách: {_fmt_vnd(slots.estimated_value_vnd)}",
            f"• Thời hạn: {slots.deadline_days or '—'} ngày",
            f"• Giao tại: {slots.delivery_location or '—'}",
            f"• NCC dự kiến: {', '.join(slots.supplier_names) or '—'}",
        ]
        if slots.purpose:
            lines.insert(1, f"• Mục đích: {slots.purpose}")
        if method is not None:
            lines.append(f"• Phương án dự kiến theo quy định: {method.label}")
        optional_missing = [
            label
            for label, value in (
                ("bảo hành", slots.warranty_months),
                ("hệ điều hành/bản quyền", slots.os_license),
                ("điều khoản thanh toán", slots.payment_terms),
            )
            if value in (None, "")
        ]
        if optional_missing:
            lines.append(
                "• Chưa nêu (DW sẽ hỏi làm rõ sau): " + ", ".join(optional_missing)
            )
        return ChatReply(
            text="Tôi hiểu yêu cầu như sau — bạn xác nhận để tạo hồ sơ nhé?",
            kind="confirm_card",
            summary_lines=tuple(lines),
            conversation_id=conversation_id,
            reasoning=reasoning,
        )

    def _case_link(self, case_id: uuid.UUID, text: str) -> ChatReply:
        url = f"{self.web_base_url.rstrip('/')}/procurement/dw01/cases/{case_id}"
        return ChatReply(text=f"{text}\nXem chi tiết: {url}", kind="case_link", case_id=case_id)
