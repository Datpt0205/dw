"""Channel-agnostic conversation service for DW01 chat intake.

Depends only on ports (store, model gateway, application handlers) — the Slack
adapter renders replies; this service never sees Slack payloads. Flow per plan:
slot-filling → deterministic completeness → confirm-before-commit → the same
``CreatePreparationCaseCommand`` the web UI uses.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC
from typing import Any, ClassVar, Literal, Protocol

from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.ports import ModelRequest, TracedModelGateway
from dw_kernel.errors import ConflictError, DomainError
from dw_kernel.ports import IdGenerator, UtcClock
from dw_platform.application.access_context import AccessContext
from dw_tender.application.conversation.schemas import (
    AddendumDraftText,
    ClarifyTurn,
    ComposedReply,
    IntakeChatTurn,
    IntakeSlots,
    missing_required,
    parse_vnd_amounts,
    render_pr_markdown,
)
from dw_tender.application.preparation.handlers import (
    AnswerPreparationClarificationsHandler,
    ClarificationAnswer,
    CreatePreparationCaseCommand,
    CreatePreparationCaseHandler,
    GetPreparationCaseHandler,
    ProposeAddendumCommand,
    ProposePreparationAddendumHandler,
    RecordPreparationSubmissionHandler,
    RecordSubmissionCommand,
    RequestCp4Handler,
    RunPreparationHandler,
)
from dw_tender.application.preparation.rules import ProcurementRules
from dw_tender.domain.preparation.entities import BusinessDomain, ProcurementType

ConversationState = Literal["collecting", "confirming", "case_created", "cancelled", "parked"]


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

    async def find_latest(
        self, *, tenant_id: uuid.UUID, workspace_id: uuid.UUID, channel_key: str
    ) -> ConversationView | None:
        """Most recent conversation on this channel regardless of state."""
        ...

    async def find_parked(
        self, *, tenant_id: uuid.UUID, workspace_id: uuid.UUID, channel_key: str
    ) -> ConversationView | None:
        """Most recent PARKED draft on this channel (mid-intake pivot)."""
        ...

    async def list_case_conversations(
        self, *, tenant_id: uuid.UUID, workspace_id: uuid.UUID, channel_key: str
    ) -> list[ConversationView]:
        """Conversations owning a live case on this channel, focus-order."""
        ...

    async def touch(self, *, conversation_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        """Bump the conversation's recency (case-picker focus switch)."""
        ...

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
    # Case picker (multi-case DMs): [(conversation_id, case title), ...]
    case_options: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class TurnOutcome:
    """One handled inbound turn: the model's visible thinking + the replies.

    ``thinking`` is the model's own reasoning trace (OpenAI Responses reasoning
    summary / DeepSeek reasoning_content) when the routed adapter surfaces one,
    else the system-built trace (ADR-020) — shown BEFORE the replies.
    """

    replies: tuple[ChatReply, ...]
    thinking: str = ""


def _fmt_vnd(value: int | None) -> str:
    return f"{value:,}".replace(",", ".") + " VND" if value else "—"


@dataclass
class ConversationIntakeService:
    store: ConversationStorePort
    gateway: TracedModelGateway
    create_case: CreatePreparationCaseHandler
    rules: ProcurementRules
    clock: UtcClock
    id_generator: IdGenerator
    # Post-publication lifecycle driven from chat (docs are GENERATED from the
    # conversation — no manual uploads). Optional so intake-only wiring works.
    # Requester-side addendum is a PROPOSAL only — procurement drafts (role fix).
    propose_addendum: ProposePreparationAddendumHandler | None = None
    record_submission: RecordPreparationSubmissionHandler | None = None
    request_cp4: RequestCp4Handler | None = None
    # Clarification loop over chat (the web form is read-only now).
    get_case: GetPreparationCaseHandler | None = None
    answer_clarifications: AnswerPreparationClarificationsHandler | None = None
    run_case: RunPreparationHandler | None = None
    model_profile: str = "balanced"
    web_base_url: str = "http://localhost:3000"
    prompt_version: str = "1.3.0"
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
    ) -> TurnOutcome:
        conversation = await self.store.find_active(
            tenant_id=context.tenant_id,
            workspace_id=context.workspace_id,
            channel_key=channel_key,
        )
        if conversation is None:
            # No intake in flight — conversations on this channel may own live
            # cases; lifecycle chat targets the most recently focused one.
            case_convs = await self.store.list_case_conversations(
                tenant_id=context.tenant_id,
                workspace_id=context.workspace_id,
                channel_key=channel_key,
            )
            if case_convs:
                lifecycle = await self._try_lifecycle_turn(
                    case_convs[0],
                    text,
                    context,
                    display_name,
                    siblings=case_convs[1:],
                )
                if lifecycle is not None:
                    return lifecycle
            conversation = await self.store.create(
                conversation_id=self.id_generator.new_uuid(),
                tenant_id=context.tenant_id,
                workspace_id=context.workspace_id,
                channel_key=channel_key,
                subject=str(context.principal_id),
            )

        turn, model_thinking = await self._run_turn(conversation, text, context, display_name)

        # Mid-intake pivot ("thôi, giờ cần mua X khác"): PARK the current draft
        # and open a fresh conversation so two requests never blend into one.
        # Deterministic trigger: new-request intent + a DIFFERENT item than the
        # draft already holds. The parked draft auto-resumes after this one
        # finishes (case created or cancelled).
        park_note = ""
        if (
            turn.intent == "create_request"
            and conversation.state in ("collecting", "confirming")
            and (conversation.slots.item_summary or "").strip()
            and (turn.slots.item_summary or "").strip()
            and (turn.slots.item_summary or "").strip().casefold()
            != (conversation.slots.item_summary or "").strip().casefold()
        ):
            parked_item = conversation.slots.item_summary
            await self.store.update(
                conversation_id=conversation.id,
                tenant_id=context.tenant_id,
                state="parked",
            )
            conversation = await self.store.create(
                conversation_id=self.id_generator.new_uuid(),
                tenant_id=context.tenant_id,
                workspace_id=context.workspace_id,
                channel_key=channel_key,
                subject=str(context.principal_id),
            )
            park_note = (
                f"⏸ Mình tạm treo hồ sơ đang khai «{parked_item}» — xong yêu cầu "
                "mới này mình sẽ tự quay lại nó nhé."
            )

        merged = conversation.slots.merged_with(turn.slots)

        # Deterministic money cross-check: if the message names an amount and
        # the LLM's conversion doesn't match any of them, do NOT trust it —
        # drop the slot and ask for the exact figure instead of mis-committing.
        money_guard = ""
        if (
            turn.slots.estimated_value_vnd is not None
            and turn.slots.estimated_value_vnd != conversation.slots.estimated_value_vnd
        ):
            mentioned = parse_vnd_amounts(text)
            if mentioned and turn.slots.estimated_value_vnd not in mentioned:
                merged = merged.model_copy(update={"estimated_value_vnd": None})
                money_guard = (
                    " Riêng ngân sách, con số tôi hiểu chưa khớp với tin nhắn — "
                    "bạn ghi rõ số tiền VND (vd: 2.000.000.000) giúp nhé?"
                )

        if turn.intent == "cancel":
            await self.store.update(
                conversation_id=conversation.id,
                tenant_id=context.tenant_id,
                state="cancelled",
            )
            cancel_reply = ChatReply(
                text=await self._compose_reply(
                    event="cancel_intake",
                    facts={"action": "đã huỷ yêu cầu mua sắm đang khai báo"},
                    fallback=("Đã huỷ yêu cầu hiện tại. Khi cần mua sắm, bạn cứ nhắn cho tôi nhé."),
                    context=context,
                    trace=f"reply-{str(conversation.id)[:8]}",
                )
            )
            resume = await self._resume_parked(channel_key, context)
            return TurnOutcome(
                replies=(cancel_reply, *((resume,) if resume else ())),
                thinking=model_thinking or "• Người dùng muốn huỷ yêu cầu hiện tại.",
            )

        missing = missing_required(merged, self.rules)
        # Visible "thinking" prefers the model's OWN reasoning trace (ADR-020:
        # OpenAI Responses reasoning summary / DeepSeek reasoning_content).
        # Providers that surface none fall back to the system-built trace, and
        # system guard lines are still appended below — they never disappear.
        thinking = model_thinking or self._build_thinking(
            before=conversation.slots, merged=merged, missing=missing
        )
        next_state: ConversationState = "collecting" if missing else "confirming"
        await self.store.update(
            conversation_id=conversation.id,
            tenant_id=context.tenant_id,
            state=next_state,
            slots=merged,
        )

        if money_guard:
            thinking += (
                "\n• ⚠️ Kiểm chéo số tiền: giá trị LLM quy đổi không khớp con số "
                "trong tin nhắn → bỏ qua, hỏi lại chính xác."
            )
        park_replies = (ChatReply(text=park_note),) if park_note else ()
        if missing:
            return TurnOutcome(
                replies=(*park_replies, ChatReply(text=turn.reply_vi + money_guard)),
                thinking=thinking,
            )
        return TurnOutcome(
            replies=(*park_replies, self._confirm_card(conversation.id, merged)),
            thinking=thinking,
        )

    # -------------------------------------------------------------- actions --
    async def handle_action(
        self,
        *,
        action: Literal["confirm", "edit"],
        conversation_id: uuid.UUID,
        context: AccessContext,
        display_name: str,
    ) -> TurnOutcome:
        conversation = await self.store.get(
            conversation_id=conversation_id, tenant_id=context.tenant_id
        )
        if conversation is None:
            return TurnOutcome(
                replies=(ChatReply(text="Không tìm thấy phiên trao đổi này (có thể đã hết hạn)."),)
            )
        # Stale/double click: once the case exists, just repeat the link.
        if conversation.state == "case_created" and conversation.case_id:
            return TurnOutcome(
                replies=(self._case_link(conversation.case_id, "Hồ sơ đã được tạo trước đó."),)
            )
        if conversation.state != "confirming":
            return TurnOutcome(
                replies=(
                    ChatReply(
                        text="Phiên này chưa ở bước xác nhận — bạn bổ sung thông tin đã nhé."
                    ),
                )
            )

        if action == "edit":
            await self.store.update(
                conversation_id=conversation.id,
                tenant_id=context.tenant_id,
                state="collecting",
            )
            return TurnOutcome(
                replies=(
                    ChatReply(
                        text=(
                            "OK, bạn nhắn phần muốn sửa (vd: «ngân sách 1,5 tỷ» hoặc "
                            "«thêm NCC FPT») — mình cập nhật rồi xác nhận lại nhé."
                        )
                    ),
                )
            )

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
        resume = await self._resume_parked(conversation.channel_key, context)
        return TurnOutcome(
            replies=(
                self._case_link(
                    case_id,
                    "✅ Mình đã tạo hồ sơ và gửi quản lý xác minh. "
                    "Duyệt xong là mình chạy luôn — có tiến độ mới mình nhắn bạn "
                    "ngay tại đây nhé.",
                ),
                *((resume,) if resume else ()),
            )
        )

    async def _resume_parked(self, channel_key: str, context: AccessContext) -> ChatReply | None:
        """Reactivate the most recent parked draft on this channel (if any)."""
        parked = await self.store.find_parked(
            tenant_id=context.tenant_id,
            workspace_id=context.workspace_id,
            channel_key=channel_key,
        )
        if parked is None:
            return None
        await self.store.update(
            conversation_id=parked.id, tenant_id=context.tenant_id, state="collecting"
        )
        missing = missing_required(parked.slots, self.rules)
        item = parked.slots.item_summary or parked.slots.title or "yêu cầu trước"
        tail = (
            "Còn thiếu: " + "; ".join(missing)
            if missing
            else "Thông tin đã đủ — mình chốt lại nhé."
        )
        return ChatReply(text=f"▶️ Quay lại hồ sơ đang khai dở «{item}». {tail}")

    # ----------------------------------------------------- lifecycle (P4b) ---
    async def _try_lifecycle_turn(
        self,
        conversation: ConversationView,
        text: str,
        context: AccessContext,
        display_name: str,
        siblings: list[ConversationView] | None = None,
    ) -> TurnOutcome | None:
        """Route post-publication intents on an existing case.

        Returns None when the message is a NEW purchase request — the caller
        then opens a fresh intake conversation. Documents (addendum, biên nhận)
        are GENERATED from the conversation and stored through the same
        handlers the web upload used — no manual files.
        """
        case_id = conversation.case_id
        assert case_id is not None

        # 🔴 Clarification loop: with the web form read-only, chat is the ONLY
        # way to answer — a dedicated mapping turn, then auto-continue the run.
        if self.get_case is not None and self.answer_clarifications is not None:
            view = await self.get_case.handle(case_id, context)
            if view.state == "waiting_clarification":
                return await self._clarify_flow(view, case_id, text, context, display_name)

        turn, model_thinking = await self._run_turn(conversation, text, context, display_name)
        outcome = await self._lifecycle_action(
            turn, model_thinking, conversation, case_id, text, context, display_name
        )
        if outcome is None:
            return None
        return await self._with_picker(outcome, conversation, siblings or [], context)

    async def _lifecycle_action(
        self,
        turn: IntakeChatTurn,
        model_thinking: str,
        conversation: ConversationView,
        case_id: uuid.UUID,
        text: str,
        context: AccessContext,
        display_name: str,
    ) -> TurnOutcome | None:
        if turn.intent == "request_addendum" and self.propose_addendum is not None:
            # Role fix: the requester only PROPOSES a change — procurement
            # (Bình) decides whether to draft the addendum and file CP3.
            change = (turn.addendum.change_summary if turn.addendum else "").strip() or text
            impact = (turn.addendum.impact_summary if turn.addendum else "").strip()
            try:
                await self.propose_addendum.handle(
                    case_id,
                    ProposeAddendumCommand(
                        change_summary=change,
                        impact_summary=impact,
                        proposer_name=display_name,
                    ),
                    context,
                )
            except (ConflictError, DomainError):
                return TurnOutcome(
                    replies=(
                        ChatReply(
                            text=await self._compose_reply(
                                event="addendum_rejected",
                                facts={
                                    "reason": (
                                        "hồ sơ chưa phát hành hoặc đã qua giai đoạn nhận sửa đổi"
                                    )
                                },
                                fallback=(
                                    "Hiện chưa gửi được đề nghị sửa đổi — hồ sơ phải ở "
                                    "trạng thái đã phát hành."
                                ),
                                context=context,
                                trace=f"reply-{str(case_id)[:8]}",
                            )
                        ),
                    )
                )
            return TurnOutcome(
                replies=(
                    ChatReply(
                        text=await self._compose_reply(
                            event="addendum_proposed",
                            facts={
                                "change": change[:200],
                                "next_step": (
                                    "bộ phận mua sắm xem xét; nếu hợp lệ sẽ lập addendum "
                                    "và trình CP3 — bạn sẽ được báo kết quả"
                                ),
                            },
                            fallback=(
                                "Đã chuyển đề nghị sửa đổi của bạn tới bộ phận mua sắm. "
                                "Nếu được chấp thuận, văn bản addendum sẽ được lập và "
                                "trình duyệt CP3 — mình sẽ báo bạn kết quả."
                            ),
                            context=context,
                            trace=f"reply-{str(case_id)[:8]}",
                        )
                    ),
                ),
                thinking=model_thinking
                or (
                    "• Nhận diện đề nghị sửa đổi sau phát hành từ người yêu cầu.\n"
                    f"• Nội dung: {change[:160]}\n"
                    "• Chuyển bộ phận mua sắm quyết định lập addendum (SoD: người "
                    "yêu cầu không tự lập hồ sơ CP3)."
                ),
            )

        if turn.intent == "record_submission" and self.record_submission is not None:
            supplier = (turn.submission.supplier_name if turn.submission else "").strip()
            if not supplier:
                return TurnOutcome(
                    replies=(
                        ChatReply(
                            text=await self._compose_reply(
                                event="submission_missing_supplier",
                                facts={"need": "tên nhà cung cấp đã nộp hồ sơ dự thầu"},
                                fallback="Bạn cho tôi biết tên nhà cung cấp đã nộp hồ sơ nhé?",
                                context=context,
                                trace=f"reply-{str(case_id)[:8]}",
                            )
                        ),
                    )
                )
            reference = (turn.submission.external_reference if turn.submission else "").strip()
            now = self.clock.now().astimezone(UTC)
            receipt = (
                f"# Biên nhận hồ sơ dự thầu\n\n"
                f"- Nhà cung cấp: {supplier}\n"
                f"- Tham chiếu: {reference or '—'}\n"
                f"- Thời điểm tiếp nhận: {now:%d/%m/%Y %H:%M}\n"
                f"- Ghi nhận bởi: {display_name} (qua Slack)\n"
            )
            try:
                await self.record_submission.handle(
                    case_id,
                    RecordSubmissionCommand(
                        filename=f"submission-{supplier.lower().replace(' ', '-')}.md",
                        content_type="text/markdown; charset=utf-8",
                        content=receipt.encode("utf-8"),
                        supplier_name=supplier,
                        received_at=now.isoformat(),
                        receipt_status="on_time",
                        external_reference=reference,
                    ),
                    context,
                )
            except (ConflictError, DomainError):
                return TurnOutcome(
                    replies=(
                        ChatReply(
                            text=await self._compose_reply(
                                event="submission_rejected",
                                facts={
                                    "reason": "hồ sơ đang không ở giai đoạn tiếp nhận HSDT",
                                    "next_step": "phát hành hồ sơ mời thầu trước",
                                },
                                fallback=(
                                    "Hồ sơ đang không ở giai đoạn tiếp nhận HSDT nên mình "
                                    "chưa ghi nhận được — cần phát hành hồ sơ mời thầu "
                                    "trước đã nhé."
                                ),
                                context=context,
                                trace=f"reply-{str(case_id)[:8]}",
                            )
                        ),
                    )
                )
            return TurnOutcome(
                replies=(
                    ChatReply(
                        text=await self._compose_reply(
                            event="submission_recorded",
                            facts={
                                "supplier": supplier,
                                "reference": reference or "(không có)",
                                "stored": "biên nhận đã lưu vào sổ tiếp nhận",
                            },
                            fallback=(
                                f"Đã ghi nhận hồ sơ dự thầu của {supplier} và lưu biên nhận "
                                "vào sổ tiếp nhận."
                            ),
                            context=context,
                            trace=f"reply-{str(case_id)[:8]}",
                        )
                    ),
                ),
                thinking=model_thinking
                or (
                    f"• Ghi nhận HSDT từ «{supplier}»"
                    + (f" (tham chiếu {reference})" if reference else "")
                    + ".\n• Biên nhận được hệ thống tự lập và niêm phong vào hồ sơ."
                ),
            )

        if turn.intent == "open_bids" and self.request_cp4 is not None:
            try:
                count = await self.request_cp4.handle(case_id, context)
            except (ConflictError, DomainError):
                return TurnOutcome(
                    replies=(
                        ChatReply(
                            text=await self._compose_reply(
                                event="open_bids_rejected",
                                facts={
                                    "reason": (
                                        "sổ tiếp nhận trống hoặc hồ sơ chưa ở giai đoạn nhận HSDT"
                                    ),
                                    "next_step": (
                                        "báo từng nhà cung cấp đã nộp trước, "
                                        "ví dụ: Synnex FPT vừa nộp hồ sơ"
                                    ),
                                },
                                fallback=(
                                    "Chưa có hồ sơ dự thầu nào trong sổ tiếp nhận nên mình "
                                    "chưa trình mở thầu được. Bạn báo từng nhà cung cấp đã "
                                    "nộp trước nhé — ví dụ: Synnex FPT vừa nộp hồ sơ."
                                ),
                                context=context,
                                trace=f"reply-{str(case_id)[:8]}",
                            )
                        ),
                    ),
                    thinking=model_thinking
                    or (
                        "• Yêu cầu mở thầu nhưng sổ tiếp nhận trống hoặc hồ sơ chưa "
                        "ở giai đoạn nhận HSDT → hướng dẫn báo nộp trước."
                    ),
                )
            return TurnOutcome(
                replies=(
                    ChatReply(
                        text=await self._compose_reply(
                            event="open_bids_requested",
                            facts={
                                "submissions": str(count),
                                "next_step": (
                                    "Quản lý xác nhận CP4 qua thẻ Slack; khi xác nhận, "
                                    "biên bản mở thầu và gói bàn giao DW02 lập tự động"
                                ),
                            },
                            fallback=(
                                f"Đã đề nghị chốt sổ với {count} hồ sơ dự thầu và mở thầu. "
                                "Quản lý sẽ nhận thẻ xác nhận CP4 trên Slack — khi xác nhận, "
                                "biên bản mở thầu và gói bàn giao DW02 sẽ được lập tự động."
                            ),
                            context=context,
                            trace=f"reply-{str(case_id)[:8]}",
                        )
                    ),
                ),
                thinking=model_thinking
                or (
                    f"• Sổ tiếp nhận có {count} hồ sơ dự thầu.\n"
                    "• CP4 cần người có thẩm quyền xác nhận (SoD) → gửi thẻ cho Quản lý."
                ),
            )

        if turn.intent == "ask_status":
            facts = {"info": "gửi link trang hồ sơ"}
            if self.get_case is not None:
                try:
                    view = await self.get_case.handle(case_id, context)
                    facts = {"title": view.title, "state": str(view.state)}
                except Exception:
                    pass
            return TurnOutcome(
                replies=(
                    self._case_link(
                        case_id,
                        await self._compose_reply(
                            event="status_summary",
                            facts=facts,
                            fallback="Trạng thái chi tiết của hồ sơ:",
                            context=context,
                            trace=f"reply-{str(case_id)[:8]}",
                        ),
                    ),
                ),
                thinking=model_thinking,
            )
        if turn.intent == "create_request":
            return None  # new purchase → caller opens a fresh intake conversation
        return TurnOutcome(replies=(ChatReply(text=turn.reply_vi),))

    async def _case_title(self, case_id: uuid.UUID, context: AccessContext) -> str:
        if self.get_case is None:
            return str(case_id)[:8]
        try:
            return (await self.get_case.handle(case_id, context)).title
        except Exception:
            return str(case_id)[:8]

    async def _with_picker(
        self,
        outcome: TurnOutcome,
        target: ConversationView,
        siblings: list[ConversationView],
        context: AccessContext,
    ) -> TurnOutcome:
        """Multi-case DM: say which case was targeted + offer a focus switch."""
        if not siblings:
            return outcome
        target_title = await self._case_title(target.case_id, context) if target.case_id else "?"
        options: list[tuple[str, str]] = []
        for sib in siblings[:3]:
            if sib.case_id is None:
                continue
            options.append((str(sib.id), await self._case_title(sib.case_id, context)))
        picker = ChatReply(
            text=(
                f"Áp dụng cho hồ sơ «{target_title}». Nhầm hồ sơ? "
                "Chọn hồ sơ khác bên dưới rồi nhắn lại yêu cầu."
            ),
            case_options=tuple(options),
        )
        return TurnOutcome(replies=(*outcome.replies, picker), thinking=outcome.thinking)

    async def handle_pick_case(
        self, *, conversation_id: uuid.UUID, context: AccessContext
    ) -> TurnOutcome:
        """Case-picker button: switch chat focus to the chosen conversation."""
        conversation = await self.store.get(
            conversation_id=conversation_id, tenant_id=context.tenant_id
        )
        if conversation is None or conversation.case_id is None:
            return TurnOutcome(replies=(ChatReply(text="Không tìm thấy hồ sơ này nữa."),))
        await self.store.touch(conversation_id=conversation_id, tenant_id=context.tenant_id)
        title = await self._case_title(conversation.case_id, context)
        return TurnOutcome(
            replies=(
                ChatReply(
                    text=(
                        f"✅ Đã chuyển ngữ cảnh sang hồ sơ «{title}» — bạn nhắn lại "
                        "yêu cầu giúp nhé."
                    )
                ),
            )
        )

    async def _clarify_flow(
        self,
        view: Any,
        case_id: uuid.UUID,
        text: str,
        context: AccessContext,
        display_name: str,
    ) -> TurnOutcome:
        """Map a natural reply onto the pending clarification questions."""
        items: list[dict[str, Any]] = []
        for artifact in view.artifacts:
            if artifact.artifact_type == "clarification_list":
                items = [
                    dict(item)
                    for item in artifact.content.get("items", [])
                    if isinstance(item, dict)
                ]
        pending = [item for item in items if item.get("blocking")]
        if not pending:
            return TurnOutcome(
                replies=(
                    ChatReply(
                        text=await self._compose_reply(
                            event="no_pending_clarifications",
                            facts={"state": "không còn câu hỏi làm rõ, workflow chạy tiếp"},
                            fallback="Không còn câu hỏi làm rõ nào — mình chạy tiếp đây.",
                            context=context,
                            trace=f"reply-{str(case_id)[:8]}",
                        )
                    ),
                )
            )
        questions_text = "\n".join(
            f"- {item.get('id')} | {item.get('question')} | gợi ý: "
            f"{item.get('suggested_answer') or '(không có)'}"
            for item in pending
        )
        run_context = self._agent_run_context(context, trace=f"clarify-{str(case_id)[:8]}")
        turn, model_thinking = await self.gateway.generate_structured_traced(
            ModelRequest(
                task="conversation.clarify_answers",
                prompt_id="conversation.clarify_answers",
                prompt_version="1.0.0",
                variables={
                    "questions": questions_text,
                    "message": text,
                    "display_name": display_name,
                },
                model_profile=self.model_profile,
            ),
            ClarifyTurn,
            run_context=run_context,
        )
        model_thinking = model_thinking.strip()
        valid_ids = {str(item.get("id")) for item in pending}
        answers = tuple(
            ClarificationAnswer(
                clarification_id=item.clarification_id,
                question=next(
                    (
                        str(p.get("question", ""))
                        for p in pending
                        if str(p.get("id")) == item.clarification_id
                    ),
                    "",
                ),
                answer=item.answer.strip(),
                source_note=f"Trả lời qua Slack bởi {display_name}",
            )
            for item in turn.answers
            if item.clarification_id in valid_ids and item.answer.strip()
        )
        if not answers:
            return TurnOutcome(
                replies=(ChatReply(text=turn.reply_vi),),
                thinking=model_thinking
                or (
                    f"• {len(pending)} câu hỏi làm rõ đang chờ; tin nhắn chưa trả lời "
                    "được câu nào → hỏi lại."
                ),
            )
        await self.answer_clarifications.handle(case_id, answers, context)  # type: ignore[union-attr]
        remaining = len(pending) - len(answers)
        thinking = model_thinking or (
            f"• Ghi nhận {len(answers)}/{len(pending)} câu trả lời làm rõ (lưu "
            "CLARIFICATION_RESPONSE).\n"
            + (
                f"• Còn {remaining} câu chưa trả lời → sẽ hỏi tiếp."
                if remaining > 0
                else "• Đã đủ — khởi động lại workflow để chạy tiếp tới CP1."
            )
        )
        if remaining <= 0 and self.run_case is not None:
            await self.run_case.handle(case_id, context)
            reply_text = await self._compose_reply(
                event="clarifications_complete",
                facts={
                    "answered": f"{len(answers)}/{len(pending)} câu hỏi làm rõ",
                    "next_step": "workflow chạy tiếp, sẽ báo khi có tiến độ mới",
                },
                fallback=(
                    "✅ Đã ghi nhận đủ câu trả lời — mình chạy tiếp đây, "
                    "có tiến độ mới mình nhắn bạn ngay."
                ),
                context=context,
                trace=f"reply-{str(case_id)[:8]}",
            )
        else:
            reply_text = turn.reply_vi
        return TurnOutcome(replies=(ChatReply(text=reply_text),), thinking=thinking)

    # ------------------------------------------------------------ internals --
    async def _compose_reply(
        self,
        *,
        event: str,
        facts: dict[str, str],
        fallback: str,
        context: AccessContext,
        trace: str,
    ) -> str:
        """LLM-composed reply from system-verified facts (ADR-020 group 2).

        Presentation-only: the action already happened, so ANY model failure
        (mock without fixture, provider error, junk output) falls back to the
        deterministic template — the reply never blocks or invents facts.
        """
        try:
            composed = await self.gateway.generate_structured(
                ModelRequest(
                    task="conversation.compose_reply",
                    prompt_id="conversation.compose_reply",
                    prompt_version="1.0.0",
                    variables={
                        "event": event,
                        "facts": json.dumps(facts, ensure_ascii=False),
                        "fallback": fallback,
                    },
                    model_profile=self.model_profile,
                ),
                ComposedReply,
                run_context=self._agent_run_context(context, trace=trace),
            )
            return composed.reply_vi.strip() or fallback
        except Exception:
            return fallback

    async def _addendum_markdown(
        self,
        *,
        case_id: uuid.UUID,
        channel_key: str,
        change: str,
        impact: str,
        raw_text: str,
        display_name: str,
        context: AccessContext,
    ) -> str:
        """Addendum document: LLM-drafted body, system-built provenance.

        The metadata header and the verbatim Slack quote are ALWAYS code-built
        (auditable trail); the LLM only elaborates the change/impact sections
        and never sees authority to alter figures. On any model failure the
        body degrades to the raw statements — same content, plainer wording.
        """
        change_section, impact_section, clauses = change, impact, list[str]()
        try:
            draft = await self.gateway.generate_structured(
                ModelRequest(
                    task="conversation.draft_addendum",
                    prompt_id="conversation.draft_addendum",
                    prompt_version="1.0.0",
                    variables={
                        "case_title": await self._case_title(case_id, context),
                        "requester": display_name,
                        "change": change,
                        "impact": impact or "(người yêu cầu chưa nêu)",
                    },
                    model_profile=self.model_profile,
                ),
                AddendumDraftText,
                run_context=self._agent_run_context(context, trace=f"addm-{str(case_id)[:8]}"),
            )
            change_section = draft.change_section.strip() or change
            impact_section = draft.impact_section.strip() or impact
            clauses = [c.strip() for c in draft.affected_clauses if c.strip()]
        except Exception:
            pass
        clauses_md = (
            "\n## Hạng mục HSMT có thể bị ảnh hưởng\n\n"
            + "\n".join(f"- {c}" for c in clauses)
            + "\n"
            if clauses
            else ""
        )
        return (
            f"# Văn bản sửa đổi/làm rõ HSMT (addendum)\n\n"
            f"- Hồ sơ: {channel_key}\n"
            f"- Người yêu cầu: {display_name} (qua Slack)\n"
            f"- Ngày lập: {self.clock.now().astimezone(UTC):%d/%m/%Y %H:%M}\n\n"
            f"## Nội dung sửa đổi\n\n{change_section}\n\n"
            f"## Đánh giá ảnh hưởng\n\n"
            f"{impact_section or 'Chưa đánh giá — cần CP3 xem xét.'}\n"
            f"{clauses_md}\n"
            f"## Nguyên văn yêu cầu (Slack)\n\n> {raw_text.strip()[:600]}\n"
        )

    def _agent_run_context(self, context: AccessContext, *, trace: str) -> RunContext:
        return RunContext(
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
            trace_id=trace,
        )

    async def _run_turn(
        self,
        conversation: ConversationView,
        text: str,
        context: AccessContext,
        display_name: str,
    ) -> tuple[IntakeChatTurn, str]:
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
        run_context = self._agent_run_context(context, trace=f"chat-{str(conversation.id)[:12]}")
        # Traced call: the second element is the model's own reasoning trace
        # ("" when the routed provider surfaces none — mock, chat/completions).
        turn, reasoning = await self.gateway.generate_structured_traced(
            request, IntakeChatTurn, run_context=run_context
        )
        return turn, reasoning.strip()

    _SLOT_LABELS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("title", "tên gói"),
        ("item_summary", "hàng hoá/dịch vụ"),
        ("quantity", "số lượng"),
        ("estimated_value_vnd", "ngân sách"),
        ("deadline_days", "thời hạn"),
        ("delivery_location", "nơi giao"),
        ("purpose", "mục đích"),
        ("supplier_names", "NCC dự kiến"),
        ("warranty_months", "bảo hành"),
        ("os_license", "HĐH/bản quyền"),
        ("payment_terms", "thanh toán"),
    )

    def _build_thinking(
        self, *, before: IntakeSlots, merged: IntakeSlots, missing: list[str]
    ) -> str:
        """Deterministic reasoning trace: every line is true by construction."""
        lines: list[str] = []

        captured: list[str] = []
        for name, label in self._SLOT_LABELS:
            old, new = getattr(before, name), getattr(merged, name)
            if new in (None, "", []) or new == old:
                continue
            if name == "estimated_value_vnd":
                captured.append(f"{label} {_fmt_vnd(new)}")
            elif name == "deadline_days":
                captured.append(f"{label} {new} ngày")
            elif name == "supplier_names":
                captured.append(f"{label}: {', '.join(new)}")
            else:
                captured.append(f"{label}: {new}")
        if captured:
            lines.append("• Ghi nhận từ tin nhắn: " + "; ".join(captured))
        else:
            lines.append("• Tin nhắn không bổ sung thông tin mới cho hồ sơ.")

        if merged.estimated_value_vnd:
            method = self.rules.select_method(merged.estimated_value_vnd)
            lines.append(
                f"• Đối chiếu quy định: giá trị {_fmt_vnd(merged.estimated_value_vnd)} "
                f"→ hình thức {method.label}, tối thiểu {method.min_suppliers} NCC "
                f"(đang có {len(merged.supplier_names)})."
            )
        else:
            lines.append(
                "• Chưa có ngân sách nên chưa đối chiếu được hình thức mua sắm theo quy định."
            )

        if missing:
            lines.append(f"• Còn thiếu {len(missing)} thông tin bắt buộc → hỏi bổ sung.")
        else:
            lines.append("• Đã đủ thông tin bắt buộc → chuyển sang bước xác nhận để tạo hồ sơ.")
        return "\n".join(lines)

    def _confirm_card(self, conversation_id: uuid.UUID, slots: IntakeSlots) -> ChatReply:
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
            lines.append("• Chưa nêu (DW sẽ hỏi làm rõ sau): " + ", ".join(optional_missing))
        return ChatReply(
            text="Tôi hiểu yêu cầu như sau — bạn xác nhận để tạo hồ sơ nhé?",
            kind="confirm_card",
            summary_lines=tuple(lines),
            conversation_id=conversation_id,
        )

    def _case_link(self, case_id: uuid.UUID, text: str) -> ChatReply:
        url = f"{self.web_base_url.rstrip('/')}/procurement/dw01/cases/{case_id}"
        return ChatReply(text=f"{text}\nXem chi tiết: {url}", kind="case_link", case_id=case_id)
