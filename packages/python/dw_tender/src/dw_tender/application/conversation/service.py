"""Channel-agnostic conversation service for DW01 chat intake.

Depends only on ports (store, model gateway, application handlers) — the Slack
adapter renders replies; this service never sees Slack payloads. Flow per plan:
slot-filling → deterministic completeness → confirm-before-commit → the same
``CreatePreparationCaseCommand`` the web UI uses.
"""

from __future__ import annotations

import json
import re
import unicodedata
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
    CaseOverviewReply,
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
    ListPreparationCasesHandler,
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

# Juggling several requests: the MODEL decides the user wants to switch
# (intent=switch_request, however they phrase it) and names the target; the
# code below decides WHICH conversation that name refers to and moves the
# state. Same split as everywhere else — LLM understands, code decides.
# Words that carry no identity ("mua 5 ghế" → "ghe" is the discriminator).
_LABEL_STOPWORDS = frozenset(
    {
        "mua","cho","cua","cai","bo","cac","moi","voi","va","ho","so","hoso","yeu","cau",
        "them","tai","tren","duoc","nhan","vien","phong","ban","cong","ty","don","vi",
        "sam","dung","can","the","nay","kia","do","lai","tiep","quay","ve",
    }
)  # fmt: skip


def _fold(text: str) -> str:
    """Accent- and case-insensitive form for matching Vietnamese labels."""
    lowered = text.casefold().replace("đ", "d")
    decomposed = unicodedata.normalize("NFD", lowered)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def _label_tokens(label: str) -> set[str]:
    return {
        token
        for token in re.split(r"[^0-9a-z]+", _fold(label))
        if len(token) >= 3 and token not in _LABEL_STOPWORDS
    }


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

    async def list_open(
        self, *, tenant_id: uuid.UUID, workspace_id: uuid.UUID, channel_key: str
    ) -> list[ConversationView]:
        """Everything still unfinished on this channel — drafts (collecting/
        confirming/parked) AND live cases — most recently focused first."""
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

    ``thinking`` is the model's OWN summary of its reasoning — the Vietnamese
    ``reasoning_summary`` it writes into the turn schema — falling back to the
    system-built trace (ADR-020). The provider's raw reasoning trace is traced
    for observability but never shown: it is internal deliberation, in English,
    and not written to be read by the requester.
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
    # Portfolio question ("hồ sơ tới đâu rồi?"). Visibility is decided here,
    # not by the model: approvers see the workspace, requesters see their own.
    list_cases: ListPreparationCasesHandler | None = None
    answer_clarifications: AnswerPreparationClarificationsHandler | None = None
    run_case: RunPreparationHandler | None = None
    model_profile: str = "balanced"
    web_base_url: str = "http://localhost:3000"
    prompt_version: str = "1.5.0"
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
        # Everything still unfinished on this channel — the model sees this
        # list so it can tell "a new request" from "back to the laptop one".
        open_convs = await self.store.list_open(
            tenant_id=context.tenant_id,
            workspace_id=context.workspace_id,
            channel_key=channel_key,
        )
        conversation = await self.store.find_active(
            tenant_id=context.tenant_id,
            workspace_id=context.workspace_id,
            channel_key=channel_key,
        )
        if conversation is None:
            # No intake in flight — conversations on this channel may own live
            # cases; lifecycle chat targets the most recently focused one.
            case_convs = [c for c in open_convs if c.state == "case_created" and c.case_id]
            if case_convs:
                lifecycle = await self._try_lifecycle_turn(
                    case_convs[0],
                    text,
                    context,
                    display_name,
                    siblings=case_convs[1:],
                    open_convs=open_convs,
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
            open_convs = [conversation, *open_convs]

        turn, model_thinking = await self._run_turn(
            conversation, text, context, display_name, open_convs
        )

        # "Quay lại vụ laptop" / "đang dở những gì?" — resolve BEFORE any slot
        # from this message is merged, so nothing leaks into the wrong request.
        focus = await self._focus_from_turn(
            turn, conversation, open_convs, text, context, display_name, model_thinking
        )
        if focus is not None:
            return focus

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
            # Safety net for when the model reads "giờ mua laptop tiếp" as a
            # brand-new request: if the item matches a draft parked earlier,
            # CONTINUE that one instead of starting from scratch.
            resumed = self._match_conversation(
                turn.slots.item_summary or "",
                [c for c in open_convs if c.id != conversation.id and c.state == "parked"],
            )
            if resumed is not None:
                await self.store.update(
                    conversation_id=resumed.id,
                    tenant_id=context.tenant_id,
                    state="collecting",
                )
                conversation = resumed
                park_note = (
                    f"⏸ Tạm treo «{parked_item}».\n"
                    f"▶️ Quay lại hồ sơ đang khai dở «{self._conv_label(resumed)}» — "
                    "mình giữ nguyên những gì đã khai."
                )
            else:
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

    # ------------------------------------------------- focus across cases ----
    def _conv_label(self, conversation: ConversationView) -> str:
        return (
            conversation.slots.item_summary
            or conversation.slots.title
            or (str(conversation.case_id)[:8] if conversation.case_id else "yêu cầu chưa đặt tên")
        )

    def _has_content(self, conversation: ConversationView) -> bool:
        return bool(
            conversation.case_id
            or (conversation.slots.item_summary or "").strip()
            or (conversation.slots.title or "").strip()
        )

    def _conv_status(self, conversation: ConversationView) -> str:
        if conversation.state == "case_created":
            return "hồ sơ đã tạo, đang chạy"
        missing = missing_required(conversation.slots, self.rules)
        if conversation.state == "confirming":
            return "chờ bạn xác nhận để tạo hồ sơ"
        return f"đang khai dở, thiếu {len(missing)} mục" if missing else "đã đủ thông tin"

    def _render_open_requests(
        self, current: ConversationView, open_convs: list[ConversationView]
    ) -> str:
        """The unfinished-work list the model reads (current one first)."""
        ordered = [c for c in open_convs if c.id == current.id] + [
            c for c in open_convs if c.id != current.id and self._has_content(c)
        ]
        lines = [
            f"- {self._conv_label(c)} ({self._conv_status(c)})"
            + (" ← đang làm" if c.id == current.id else "")
            for c in ordered[:6]
            if self._has_content(c) or c.id == current.id
        ]
        return "\n".join(lines) or "(chưa có yêu cầu nào)"

    def _match_conversation(
        self, text: str, candidates: list[ConversationView]
    ) -> ConversationView | None:
        """Pick the conversation the message names, by label overlap.

        Deterministic and accent-insensitive: "quay lai vu laptop" matches the
        draft whose item summary is "laptop cho nhân viên". Returns None when
        nothing matches — the caller then asks instead of guessing.
        """
        folded = _fold(text)
        best: tuple[int, ConversationView] | None = None
        for candidate in candidates:
            tokens = _label_tokens(self._conv_label(candidate))
            score = sum(1 for token in tokens if token in folded)
            if score and (best is None or score > best[0]):
                best = (score, candidate)
        return best[1] if best else None

    async def _focus_from_turn(
        self,
        turn: IntakeChatTurn,
        current: ConversationView,
        open_convs: list[ConversationView],
        text: str,
        context: AccessContext,
        display_name: str = "",
        model_thinking: str = "",
    ) -> TurnOutcome | None:
        """Act on the model's switch/list intent — code picks the target."""
        if turn.intent == "list_cases":
            return await self._case_overview_outcome(text, context, display_name, model_thinking)
        if turn.intent == "list_requests":
            return self._open_list_outcome(open_convs)
        if turn.intent != "switch_request":
            return None
        candidates = [c for c in open_convs if c.id != current.id]
        if not candidates:
            return None  # nothing to switch to — handle as a normal message
        target = self._match_conversation(turn.target_request or text, candidates)
        if target is None:
            # The model saw the intent but not which one — ask, never guess.
            return self._open_list_outcome(open_convs)
        return await self._focus(target, open_convs, context)

    async def _focus(
        self,
        target: ConversationView,
        open_convs: list[ConversationView],
        context: AccessContext,
    ) -> TurnOutcome:
        """Make ``target`` the conversation this channel is working on."""
        for conversation in open_convs:
            if conversation.id == target.id or conversation.state not in (
                "collecting",
                "confirming",
            ):
                continue
            # An empty draft (the turn that only said "quay lại …") is closed,
            # not parked — otherwise the list fills up with nameless entries.
            await self.store.update(
                conversation_id=conversation.id,
                tenant_id=context.tenant_id,
                state="parked" if self._has_content(conversation) else "cancelled",
            )
        if target.state == "parked":
            await self.store.update(
                conversation_id=target.id, tenant_id=context.tenant_id, state="collecting"
            )
        else:
            await self.store.touch(conversation_id=target.id, tenant_id=context.tenant_id)

        label = self._conv_label(target)
        if target.state == "case_created" and target.case_id is not None:
            title = await self._case_title(target.case_id, context)
            return TurnOutcome(
                replies=(
                    self._case_link(
                        target.case_id,
                        f"▶️ Đã chuyển sang hồ sơ «{title}». Bạn nhắn tiếp yêu cầu "
                        "cho hồ sơ này nhé.",
                    ),
                )
            )
        missing = missing_required(target.slots, self.rules)
        tail = (
            "Còn thiếu: " + "; ".join(missing)
            if missing
            else "Thông tin đã đủ — bạn nhắn «đồng ý» là mình tạo hồ sơ."
        )
        return TurnOutcome(
            replies=(
                ChatReply(
                    text=(
                        f"▶️ Quay lại hồ sơ đang khai dở «{label}» "
                        f"(giữ nguyên phần đã khai).\n{tail}"
                    )
                ),
            )
        )

    # Vietnamese labels for every case state the portfolio answer may show.
    _STATE_LABELS: ClassVar[dict[str, str]] = {
        "draft": "chờ xác minh đầu vào",
        "intake_rejected": "đầu vào bị từ chối",
        "intake_ready": "đã xác minh, chuẩn bị chạy",
        "analyzing": "đang phân tích yêu cầu",
        "waiting_clarification": "chờ trả lời làm rõ",
        "approach_ready": "đã có phương án, chuẩn bị trình CP1",
        "cp1_pending": "chờ duyệt CP1",
        "cp1_rejected": "CP1 bị từ chối",
        "cp1_approved": "CP1 đã duyệt",
        "building_solicitation": "đang soạn HSMT",
        "package_ready": "HSMT xong, chuẩn bị trình CP2",
        "cp2_pending": "chờ duyệt CP2",
        "cp2_rejected": "CP2 bị từ chối",
        "cp2_approved": "CP2 đã duyệt",
        "package_official": "hồ sơ chính thức, chờ phát hành",
        "published": "đã phát hành, chờ nhà cung cấp nộp",
        "cp3_pending": "chờ duyệt CP3 (addendum)",
        "receiving_bids": "đang nhận hồ sơ dự thầu",
        "cp4_ready": "chờ xác nhận mở thầu (CP4)",
        "completed": "hoàn tất",
    }
    # States where the ball is in an approver's court.
    _DECIDE_STATES: ClassVar[frozenset[str]] = frozenset(
        {"draft", "cp1_pending", "cp2_pending", "cp3_pending", "cp4_ready", "receiving_bids"}
    )

    async def _case_overview_outcome(
        self,
        text: str,
        context: AccessContext,
        display_name: str,
        model_thinking: str = "",
    ) -> TurnOutcome:
        """ "Hồ sơ tới đâu rồi?" — code fetches and filters, the model writes.

        Visibility is a code decision: someone who can decide approvals sees the
        whole workspace, everyone else sees only the cases they filed. The model
        never receives a case it is not allowed to mention.
        """
        if self.list_cases is None:
            return TurnOutcome(
                replies=(ChatReply(text="Mình chưa xem được danh sách hồ sơ ở kênh này."),)
            )
        cases = await self.list_cases.handle(context)
        can_decide = context.has_scope("approvals.decide")
        if not can_decide:
            cases = [case for case in cases if case.created_by == context.principal_id]

        completed = [c for c in cases if c.state == "completed"]
        awaiting = [c for c in cases if can_decide and c.state in self._DECIDE_STATES]
        awaiting_ids = {c.id for c in awaiting}
        in_flight = [c for c in cases if c.state != "completed" and c.id not in awaiting_ids]

        def line(case: Any) -> str:
            label = self._STATE_LABELS.get(case.state, case.state)
            owner = f" — người đề nghị: {case.owner_name}" if case.owner_name else ""
            return f"- {case.title} — {label}{owner}"

        case_lines = "\n".join(line(c) for c in (*awaiting, *in_flight, *completed)) or "(trống)"
        scope_note = (
            "toàn bộ hồ sơ trong workspace, gồm cả hồ sơ do người khác đề nghị"
            if can_decide
            else "chỉ những hồ sơ do chính họ đề nghị"
        )
        fallback = (
            f"📊 Tổng {len(cases)} hồ sơ — hoàn tất {len(completed)}, "
            f"đang chạy {len(in_flight)}, chờ bạn quyết {len(awaiting)}.\n{case_lines}"
            if cases
            else "Hiện chưa có hồ sơ nào trong phạm vi bạn xem được."
        )

        reply = fallback
        if cases:
            try:
                composed = await self.gateway.generate_structured(
                    ModelRequest(
                        task="conversation.summarize_cases",
                        prompt_id="conversation.summarize_cases",
                        prompt_version="1.0.0",
                        variables={
                            "display_name": display_name or "bạn",
                            "viewer_role": (
                                "người có thẩm quyền phê duyệt"
                                if can_decide
                                else "người đề nghị mua sắm"
                            ),
                            "scope_note": scope_note,
                            "message": text,
                            "total": str(len(cases)),
                            "completed": str(len(completed)),
                            "in_flight": str(len(in_flight)),
                            "awaiting": str(len(awaiting)),
                            "case_lines": case_lines,
                        },
                        model_profile=self.model_profile,
                    ),
                    CaseOverviewReply,
                    run_context=self._agent_run_context(context, trace="overview"),
                )
                reply = composed.reply_vi.strip() or fallback
            except Exception:
                reply = fallback  # never block the answer on the model

        return TurnOutcome(
            replies=(ChatReply(text=reply),),
            thinking=model_thinking
            or (
                f"• Truy {len(cases)} hồ sơ trong phạm vi được xem ({scope_note}).\n"
                f"• Hoàn tất {len(completed)}; đang chạy {len(in_flight)}; "
                f"chờ quyết định {len(awaiting)}."
            ),
        )

    def _open_list_outcome(self, open_convs: list[ConversationView]) -> TurnOutcome:
        """List everything unfinished + let the user switch by number."""
        if not open_convs:
            return TurnOutcome(
                replies=(ChatReply(text="Hiện bạn không có yêu cầu mua sắm nào đang dở cả."),)
            )
        named = [c for c in open_convs if self._has_content(c)]
        if not named:
            return TurnOutcome(
                replies=(ChatReply(text="Hiện bạn không có yêu cầu mua sắm nào đang dở cả."),)
            )
        options = tuple(
            (str(c.id), f"{self._conv_label(c)} — {self._conv_status(c)}") for c in named[:5]
        )
        return TurnOutcome(
            replies=(
                ChatReply(
                    text=f"📋 Bạn đang có {len(options)} việc chưa xong:",
                    case_options=options,
                ),
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
        open_convs: list[ConversationView] | None = None,
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

        turn, model_thinking = await self._run_turn(
            conversation, text, context, display_name, open_convs
        )
        focus = await self._focus_from_turn(
            turn,
            conversation,
            open_convs or [conversation],
            text,
            context,
            display_name,
            model_thinking,
        )
        if focus is not None:
            return focus
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
        """Picker («chọn 2»): switch focus to the chosen conversation.

        Works for a live case AND for a half-finished draft — picking a draft
        parks whatever else was in flight and resumes it with its slots intact.
        """
        conversation = await self.store.get(
            conversation_id=conversation_id, tenant_id=context.tenant_id
        )
        if conversation is None:
            return TurnOutcome(replies=(ChatReply(text="Không tìm thấy hồ sơ này nữa."),))
        open_convs = await self.store.list_open(
            tenant_id=context.tenant_id,
            workspace_id=context.workspace_id,
            channel_key=conversation.channel_key,
        )
        return await self._focus(conversation, open_convs, context)

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
        # Answering does NOT edit the clarification list — each turn appends a
        # new clarification_response artifact. Subtract every id answered so
        # far, or a partial answer re-asks the whole list on the next turn.
        answered_ids: set[str] = set()
        for artifact in view.artifacts:
            if artifact.artifact_type == "clarification_list":
                items = [
                    dict(item)
                    for item in artifact.content.get("items", [])
                    if isinstance(item, dict)
                ]
            elif artifact.artifact_type == "clarification_response":
                answered_ids.update(
                    str(item.get("id"))
                    for item in artifact.content.get("items", [])
                    if isinstance(item, dict) and str(item.get("answer", "")).strip()
                )
        pending = [
            item
            for item in items
            if item.get("blocking") and str(item.get("id")) not in answered_ids
        ]
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
        turn, _provider_trace = await self.gateway.generate_structured_traced(
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
                thinking=(
                    f"• {len(pending)} câu hỏi làm rõ đang chờ; tin nhắn chưa trả lời "
                    "được câu nào → hỏi lại."
                ),
            )
        await self.answer_clarifications.handle(case_id, answers, context)  # type: ignore[union-attr]
        remaining = len(pending) - len(answers)
        thinking = (
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
        open_convs: list[ConversationView] | None = None,
    ) -> tuple[IntakeChatTurn, str]:
        missing = missing_required(conversation.slots, self.rules)
        request = ModelRequest(
            task="conversation.intake_chat",
            prompt_id="conversation.intake_chat",
            prompt_version=self.prompt_version,
            variables={
                "known_slots": conversation.slots.model_dump_json(exclude_none=True),
                "missing_fields": "; ".join(missing) or "(không còn)",
                "open_requests": self._render_open_requests(conversation, open_convs or []),
                "message": text,
                "display_name": display_name,
                "today": f"{self.clock.now().astimezone(UTC):%d/%m/%Y}",
            },
            model_profile=self.model_profile,
        )
        run_context = self._agent_run_context(context, trace=f"chat-{str(conversation.id)[:12]}")
        # Traced call: the second element is the model's own reasoning trace
        # ("" when the routed provider surfaces none — mock, chat/completions).
        # The traced call still records the provider's own reasoning for
        # Langfuse. What the USER sees is turn.reasoning_summary — the model
        # writes it in Vietnamese, bounded, meant to be read (ADR-020). The raw
        # provider trace is internal deliberation in English and must not be
        # pushed into the chat verbatim.
        turn, _provider_trace = await self.gateway.generate_structured_traced(
            request, IntakeChatTurn, run_context=run_context
        )
        return turn, turn.reasoning_summary.strip()

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
        """Reply that refers to a case. ``case_id`` lets a channel decorate it
        if it wants; the text carries no URL — chat is where the work happens."""
        return ChatReply(text=text, kind="case_link", case_id=case_id)
