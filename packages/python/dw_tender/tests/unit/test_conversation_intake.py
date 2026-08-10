"""Chat intake: slot merge, deterministic completeness, confirm-before-commit."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from dw_kernel.errors import NotFoundError
from dw_platform.application.access_context import AccessContext
from dw_tender.application.conversation.schemas import (
    IntakeChatTurn,
    IntakeSlots,
    missing_required,
    render_pr_markdown,
)
from dw_tender.application.conversation.service import (
    ChatReply,
    ConversationIntakeService,
    ConversationView,
)
from dw_tender.application.preparation.rules import Method, ProcurementRules

pytestmark = pytest.mark.unit

RULES = ProcurementRules(
    version="1",
    currency="VND",
    # Ngưỡng theo Phụ lục G: <10tr trực tiếp; 10tr-5ty chào giá; >5tỷ đấu thầu.
    methods=(
        Method("direct_purchase", "Mua sắm trực tiếp", 10_000_000, 1),
        Method("rfq", "Chào giá cạnh tranh", 5_000_000_000, 3),
        Method("open_tender", "Đấu thầu", None, 3),
    ),
    weighted_total_must_equal=100,
    require_mandatory_criteria=True,
    legal_review_required_above=100_000_000,
    finance_review_required_above=5_000_000_000,
    tco_required_above=5_000_000_000,
    specialist_review_above=300_000_000,
    require_approved_pr=True,
    require_budget=True,
    require_deadline=True,
    require_owner=True,
)

TENANT = uuid.uuid4()
WORKSPACE = uuid.uuid4()

CONTEXT = AccessContext(
    tenant_id=TENANT,
    workspace_id=WORKSPACE,
    principal_id=uuid.uuid4(),
    roles=frozenset({"member"}),
    scopes=frozenset({"tender.read", "tender.write"}),
    plan_id="team",
    feature_flags=frozenset({"tender"}),
)

FULL_SLOTS = IntakeSlots(
    title="Mua 500 laptop kèm bản quyền",
    item_summary="laptop kèm bản quyền phần mềm cho nhân viên",
    quantity=500,
    estimated_value_vnd=7_500_000_000,
    deadline_days=45,
    delivery_location="Hà Nội",
    supplier_names=["FPT", "CMC", "Viettel"],
)


# ------------------------------------------------------------------ fakes ----
class FakeClock:
    def now(self) -> datetime:
        return datetime(2026, 7, 31, 9, 0, tzinfo=UTC)


class FakeIdGen:
    def new_uuid(self) -> uuid.UUID:
        return uuid.uuid4()


@dataclass
class FakeStore:
    conversations: dict[uuid.UUID, ConversationView] = field(default_factory=dict)
    claimed: set[str] = field(default_factory=set)

    async def claim_event(self, event_id: str) -> bool:
        if event_id in self.claimed:
            return False
        self.claimed.add(event_id)
        return True

    async def find_active(self, *, tenant_id, workspace_id, channel_key):
        for conv in self.conversations.values():
            if conv.channel_key == channel_key and conv.state in ("collecting", "confirming"):
                return conv
        return None

    async def find_latest(self, *, tenant_id, workspace_id, channel_key):
        matches = [c for c in self.conversations.values() if c.channel_key == channel_key]
        return matches[-1] if matches else None

    async def find_parked(self, *, tenant_id, workspace_id, channel_key):
        matches = [
            c
            for c in self.conversations.values()
            if c.channel_key == channel_key and c.state == "parked"
        ]
        return matches[-1] if matches else None

    async def list_open(self, *, tenant_id, workspace_id, channel_key):
        return [
            c
            for c in self.conversations.values()
            if c.channel_key == channel_key
            and c.state in ("collecting", "confirming", "parked", "case_created")
        ][::-1]

    async def touch(self, *, conversation_id, tenant_id):
        return None

    async def get(self, *, conversation_id, tenant_id):
        return self.conversations.get(conversation_id)

    async def create(self, *, conversation_id, tenant_id, workspace_id, channel_key, subject):
        conv = ConversationView(
            id=conversation_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            channel_key=channel_key,
            subject=subject,
            state="collecting",
            slots=IntakeSlots(),
            case_id=None,
        )
        self.conversations[conversation_id] = conv
        return conv

    async def update(self, *, conversation_id, tenant_id, state=None, slots=None, case_id=None):
        old = self.conversations[conversation_id]
        self.conversations[conversation_id] = ConversationView(
            id=old.id,
            tenant_id=old.tenant_id,
            workspace_id=old.workspace_id,
            channel_key=old.channel_key,
            subject=old.subject,
            state=state or old.state,
            slots=slots or old.slots,
            case_id=case_id or old.case_id,
        )


@dataclass
class FakeGateway:
    turn: IntakeChatTurn
    thinking: str = ""

    async def generate_structured(self, request, output_type, *, run_context):
        if output_type.__name__ in ("ComposedReply", "AddendumDraftText"):
            # Mirror the mock adapter without fixtures: presentation prompts
            # fail → the service falls back to its deterministic template.
            raise NotFoundError(
                "no mock response registered for prompt",
                details={"prompt_id": request.prompt_id},
            )
        return self.turn

    async def generate_structured_traced(self, request, output_type, *, run_context):
        return self.turn, self.thinking


@dataclass
class ComposingFakeGateway(FakeGateway):
    """Gateway whose presentation prompts succeed (real-provider behaviour)."""

    composed_reply: str = "reply soạn bởi model"

    async def generate_structured(self, request, output_type, *, run_context):
        if output_type.__name__ == "ComposedReply":
            return output_type(reply_vi=self.composed_reply)
        if output_type.__name__ == "AddendumDraftText":
            return output_type(
                change_section="Gia hạn thời hạn nộp HSDT thêm 7 ngày.",
                impact_section="Nhà cung cấp có thêm thời gian chuẩn bị.",
                affected_clauses=["Thời hạn nộp HSDT"],
            )
        return self.turn


@dataclass
class FakeCreateCase:
    created: list[Any] = field(default_factory=list)

    async def handle(self, command: Any, context: Any) -> uuid.UUID:
        self.created.append(command)
        return uuid.uuid4()


def make_service(
    store: FakeStore,
    turn: IntakeChatTurn,
    create_case: FakeCreateCase | None = None,
    thinking: str = "",
    gateway: FakeGateway | None = None,
) -> ConversationIntakeService:
    return ConversationIntakeService(
        store=store,
        gateway=gateway or FakeGateway(turn, thinking=thinking),
        create_case=create_case or FakeCreateCase(),  # type: ignore[arg-type]
        rules=RULES,
        clock=FakeClock(),
        id_generator=FakeIdGen(),
    )


# ---------------------------------------------------------------- schemas ----
def test_merge_keeps_existing_and_overrides_with_new() -> None:
    base = IntakeSlots(quantity=100, delivery_location="Hà Nội")
    update = IntakeSlots(quantity=120, estimated_value_vnd=2_000_000_000)
    merged = base.merged_with(update)
    assert merged.quantity == 120
    assert merged.delivery_location == "Hà Nội"
    assert merged.estimated_value_vnd == 2_000_000_000


def test_deadline_today_is_clamped_not_rejected() -> None:
    # "ngày 3/8" khi hôm nay là 3/8 → model trả 0 ngày; phải thành 1, không crash.
    assert IntakeSlots.model_validate({"deadline_days": 0}).deadline_days == 1
    assert IntakeSlots.model_validate({"deadline_days": -3}).deadline_days is None
    assert IntakeSlots.model_validate({"deadline_days": 60}).deadline_days == 60


def test_nonpositive_numeric_slots_are_dropped_not_rejected() -> None:
    slots = IntakeSlots.model_validate(
        {"quantity": 0, "estimated_value_vnd": 0, "warranty_months": 0}
    )
    assert slots.quantity is None
    assert slots.estimated_value_vnd is None
    assert slots.warranty_months is None


def test_missing_required_uses_rule_pack_supplier_minimum() -> None:
    slots = FULL_SLOTS.model_copy(update={"supplier_names": ["FPT"]})
    missing = missing_required(slots, RULES)
    assert any("tối thiểu 3" in item for item in missing)

    # Small direct purchase (<10tr theo Phụ lục G) only needs 1 supplier.
    small = slots.model_copy(update={"estimated_value_vnd": 5_000_000})
    assert missing_required(small, RULES) == []


def test_missing_required_empty_when_complete() -> None:
    assert missing_required(FULL_SLOTS, RULES) == []


def test_render_pr_markdown_contains_key_facts() -> None:
    text = render_pr_markdown(FULL_SLOTS, requester="Nguyễn Văn An", pr_ref="SLACK-1")
    assert "7.500.000.000 VND" in text
    assert "45 ngày" in text
    assert "- FPT" in text
    assert "Chưa nêu trong trao đổi" in text  # warranty not provided


# ---------------------------------------------------------------- service ----
async def test_incomplete_message_asks_question_and_keeps_collecting() -> None:
    store = FakeStore()
    turn = IntakeChatTurn(
        intent="create_request",
        slots=IntakeSlots(item_summary="laptop", quantity=100),
        reply_vi="Bạn cho tôi biết ngân sách và thời hạn nhé?",
        reasoning_summary="Đã nhận yêu cầu mua 100 laptop.",
    )
    outcome = await make_service(store, turn).handle_message(
        channel_key="slack:D1", text="Tôi muốn mua 100 laptop", context=CONTEXT, display_name="An"
    )
    replies = outcome.replies
    assert len(replies) == 1 and replies[0].kind == "message"
    assert "ngân sách" in replies[0].text
    # Thinking is SYSTEM-BUILT from the validated slot diff + completeness.
    assert "Ghi nhận từ tin nhắn" in outcome.thinking
    assert "số lượng: 100" in outcome.thinking
    assert "Còn thiếu" in outcome.thinking
    conv = next(iter(store.conversations.values()))
    assert conv.state == "collecting"
    assert conv.slots.quantity == 100


async def test_thinking_prefers_model_reasoning_trace() -> None:
    # ADR-020: the routed adapter's reasoning trace (OpenAI Responses summary /
    # DeepSeek reasoning_content) IS the displayed thinking when present.
    store = FakeStore()
    turn = IntakeChatTurn(
        intent="provide_info",
        slots=FULL_SLOTS,
        reply_vi="ok",
        reasoning_summary="trường schema — không phải nguồn hiển thị",
    )
    outcome = await make_service(
        store, turn, thinking="Ngân sách 7,5 tỷ vượt ngưỡng nên cần đấu thầu."
    ).handle_message(channel_key="slack:D1", text="đủ", context=CONTEXT, display_name="An")
    assert outcome.thinking.startswith("Ngân sách 7,5 tỷ")
    assert "trường schema" not in outcome.thinking


async def test_thinking_falls_back_to_system_trace_when_model_silent() -> None:
    # Providers with no reasoning trace (mock, chat/completions) keep the
    # deterministic system-built thinking — the line never disappears.
    store = FakeStore()
    turn = IntakeChatTurn(
        intent="provide_info", slots=FULL_SLOTS, reply_vi="ok", reasoning_summary=""
    )
    outcome = await make_service(store, turn, thinking="").handle_message(
        channel_key="slack:D1", text="đủ", context=CONTEXT, display_name="An"
    )
    assert "Đấu thầu" in outcome.thinking
    assert "tối thiểu 3 NCC" in outcome.thinking
    assert "Đã đủ thông tin bắt buộc" in outcome.thinking


async def test_complete_message_returns_confirm_card() -> None:
    store = FakeStore()
    turn = IntakeChatTurn(
        intent="provide_info", slots=FULL_SLOTS, reply_vi="Đã đủ thông tin.", reasoning_summary=""
    )
    outcome = await make_service(store, turn).handle_message(
        channel_key="slack:D1", text="đủ hết rồi", context=CONTEXT, display_name="An"
    )
    replies = outcome.replies
    assert replies[0].kind == "confirm_card"
    assert replies[0].conversation_id is not None
    assert any("Đấu thầu" in line for line in replies[0].summary_lines)
    conv = next(iter(store.conversations.values()))
    assert conv.state == "confirming"


async def test_confirm_creates_case_via_command_and_is_idempotent() -> None:
    store = FakeStore()
    create_case = FakeCreateCase()
    turn = IntakeChatTurn(
        intent="provide_info", slots=FULL_SLOTS, reply_vi="ok", reasoning_summary=""
    )
    service = make_service(store, turn, create_case)
    await service.handle_message(
        channel_key="slack:D1", text="đủ", context=CONTEXT, display_name="An"
    )
    conv_id = next(iter(store.conversations.keys()))

    replies = (
        await service.handle_action(
            action="confirm", conversation_id=conv_id, context=CONTEXT, display_name="An"
        )
    ).replies
    assert replies[0].kind == "case_link"
    assert len(create_case.created) == 1
    command = create_case.created[0]
    assert command.estimated_value_minor == 7_500_000_000
    assert command.supplier_names == ("FPT", "CMC", "Viettel")
    assert command.deadline == "45 ngày"
    assert "laptop" in command.pr_text

    # Double click: no second case, still returns the link.
    again = (
        await service.handle_action(
            action="confirm", conversation_id=conv_id, context=CONTEXT, display_name="An"
        )
    ).replies
    assert len(create_case.created) == 1
    assert again[0].kind == "case_link"


async def test_edit_returns_to_collecting() -> None:
    store = FakeStore()
    turn = IntakeChatTurn(
        intent="provide_info", slots=FULL_SLOTS, reply_vi="ok", reasoning_summary=""
    )
    service = make_service(store, turn)
    await service.handle_message(
        channel_key="slack:D1", text="đủ", context=CONTEXT, display_name="An"
    )
    conv_id = next(iter(store.conversations.keys()))
    replies = (
        await service.handle_action(
            action="edit", conversation_id=conv_id, context=CONTEXT, display_name="An"
        )
    ).replies
    assert store.conversations[conv_id].state == "collecting"
    assert "sửa" in replies[0].text.lower()


async def test_cancel_intent_closes_conversation() -> None:
    store = FakeStore()
    turn = IntakeChatTurn(
        intent="cancel", slots=IntakeSlots(), reply_vi="Đã huỷ.", reasoning_summary=""
    )
    outcome = await make_service(store, turn).handle_message(
        channel_key="slack:D1", text="thôi huỷ đi", context=CONTEXT, display_name="An"
    )
    conv = next(iter(store.conversations.values()))
    assert conv.state == "cancelled"
    # Compose prompt has no mock fixture → deterministic fallback reply.
    assert "Đã huỷ yêu cầu hiện tại" in outcome.replies[0].text


async def test_cancel_reply_is_llm_composed_when_provider_supports_it() -> None:
    # ADR-020 group 2: with a real provider the reply comes from the
    # compose_reply prompt fed with system-verified facts.
    store = FakeStore()
    turn = IntakeChatTurn(
        intent="cancel", slots=IntakeSlots(), reply_vi="Đã huỷ.", reasoning_summary=""
    )
    gateway = ComposingFakeGateway(turn, composed_reply="Mình đã huỷ giúp bạn rồi nha!")
    outcome = await make_service(store, turn, gateway=gateway).handle_message(
        channel_key="slack:D1", text="thôi huỷ đi", context=CONTEXT, display_name="An"
    )
    assert outcome.replies[0].text == "Mình đã huỷ giúp bạn rồi nha!"
    assert next(iter(store.conversations.values())).state == "cancelled"


def test_chat_reply_defaults() -> None:
    reply = ChatReply(text="hi")
    assert reply.kind == "message" and reply.summary_lines == ()


def test_parse_vnd_amounts_units_and_plain() -> None:
    from dw_tender.application.conversation.schemas import parse_vnd_amounts

    assert 2_000_000_000 in parse_vnd_amounts("ngân sách 2 tỷ nhé")
    assert 1_500_000_000 in parse_vnd_amounts("khoảng 1,5 tỷ")
    assert 500_000_000 in parse_vnd_amounts("tầm 500 triệu")
    assert 80_000_000 in parse_vnd_amounts("80tr thôi")
    assert 2_000_000_000 in parse_vnd_amounts("2.000.000.000 VND")
    assert parse_vnd_amounts("mua 100 laptop trong 45 ngày") == set()


async def test_money_guard_drops_mismatched_llm_value() -> None:
    store = FakeStore()
    turn = IntakeChatTurn(
        intent="provide_info",
        # LLM mis-converted "2 tỷ" into 200 triệu:
        slots=IntakeSlots(estimated_value_vnd=200_000_000),
        reply_vi="Đã ghi nhận ngân sách.",
        reasoning_summary="",
    )
    outcome = await make_service(store, turn).handle_message(
        channel_key="slack:D1", text="ngân sách 2 tỷ", context=CONTEXT, display_name="An"
    )
    conv = next(iter(store.conversations.values()))
    assert conv.slots.estimated_value_vnd is None  # mismatch -> dropped, not committed
    assert "chưa khớp" in outcome.replies[0].text
    assert "Kiểm chéo số tiền" in outcome.thinking


# --------------------------------------------------- mid-intake pivot ----
@dataclass
class SequenceGateway(FakeGateway):
    """Returns scripted turns in order (multi-message scenarios)."""

    turns: list[IntakeChatTurn] = field(default_factory=list)

    async def generate_structured_traced(self, request, output_type, *, run_context):
        return self.turns.pop(0), self.thinking


def _laptop_partial() -> IntakeChatTurn:
    return IntakeChatTurn(
        intent="provide_info",
        slots=IntakeSlots(item_summary="laptop cho nhân viên", quantity=500),
        reply_vi="Bạn cho mình ngân sách và thời hạn nhé?",
        reasoning_summary="",
    )


def _pivot_to_chairs() -> IntakeChatTurn:
    return IntakeChatTurn(
        intent="create_request",
        slots=IntakeSlots(item_summary="ghế văn phòng", quantity=5),
        reply_vi="OK, mình ghi nhận yêu cầu mua ghế mới nhé.",
        reasoning_summary="",
    )


async def test_new_request_mid_intake_parks_old_draft_and_opens_fresh() -> None:
    store = FakeStore()
    gw = SequenceGateway(turn=_laptop_partial(), turns=[_laptop_partial(), _pivot_to_chairs()])
    service = make_service(store, _laptop_partial(), gateway=gw)
    await service.handle_message(
        channel_key="zalo:1", text="mua 500 laptop", context=CONTEXT, display_name="An"
    )
    outcome = await service.handle_message(
        channel_key="zalo:1", text="thôi, giờ cần mua 5 ghế", context=CONTEXT, display_name="An"
    )
    states = {c.state for c in store.conversations.values()}
    assert "parked" in states  # laptop draft is parked, not blended
    convs = list(store.conversations.values())
    parked = next(c for c in convs if c.state == "parked")
    active = next(c for c in convs if c.state == "collecting")
    assert parked.slots.item_summary == "laptop cho nhân viên"
    assert active.slots.item_summary == "ghế văn phòng"
    assert active.slots.quantity == 5
    assert any("tạm treo" in r.text for r in outcome.replies)


async def _two_open_drafts() -> tuple[FakeStore, ConversationIntakeService]:
    """laptop draft parked behind an active chairs draft (the pivot scenario)."""
    store = FakeStore()
    gw = SequenceGateway(turn=_laptop_partial(), turns=[_laptop_partial(), _pivot_to_chairs()])
    service = make_service(store, _laptop_partial(), gateway=gw)
    await service.handle_message(
        channel_key="zalo:1", text="mua 500 laptop", context=CONTEXT, display_name="An"
    )
    await service.handle_message(
        channel_key="zalo:1", text="thôi, giờ cần mua 5 ghế", context=CONTEXT, display_name="An"
    )
    return store, service


def _by_item(store: FakeStore, needle: str) -> ConversationView:
    return next(c for c in store.conversations.values() if needle in (c.slots.item_summary or ""))


def _switch_turn(target: str) -> IntakeChatTurn:
    """What the model returns for "quay lại vụ laptop" / "làm nốt cái ghế"."""
    return IntakeChatTurn(
        intent="switch_request",
        slots=IntakeSlots(),
        target_request=target,
        reply_vi="",
        reasoning_summary="",
    )


def _list_turn() -> IntakeChatTurn:
    return IntakeChatTurn(
        intent="list_requests", slots=IntakeSlots(), reply_vi="", reasoning_summary=""
    )


async def test_switch_to_named_draft_parks_the_other() -> None:
    store, service = await _two_open_drafts()
    service.gateway.turns.append(_switch_turn("laptop cho nhân viên"))  # type: ignore[attr-defined]
    outcome = await service.handle_message(
        channel_key="zalo:1", text="thôi quay lại vụ laptop đi", context=CONTEXT, display_name="An"
    )
    laptop = _by_item(store, "laptop")
    chairs = _by_item(store, "ghế")
    assert laptop.state == "collecting"  # resumed with its slots intact
    assert laptop.slots.quantity == 500
    assert chairs.state == "parked"  # the other one is put on hold, not lost
    assert any("laptop" in reply.text for reply in outcome.replies)


async def test_switch_matches_target_by_wording_not_exact_label() -> None:
    """The model may name the item loosely — code still resolves it."""
    store, service = await _two_open_drafts()
    service.gateway.turns.append(_switch_turn("laptop"))  # type: ignore[attr-defined]
    await service.handle_message(
        channel_key="zalo:1", text="mở lại đơn máy tính hôm nãy", context=CONTEXT, display_name="An"
    )
    laptop = _by_item(store, "laptop")
    assert laptop.state == "collecting"


async def test_switch_without_a_target_asks_instead_of_guessing() -> None:
    _store, service = await _two_open_drafts()
    service.gateway.turns.append(_switch_turn(""))  # type: ignore[attr-defined]
    outcome = await service.handle_message(
        channel_key="zalo:1", text="quay lại cái kia đi", context=CONTEXT, display_name="An"
    )
    options = outcome.replies[0].case_options
    assert len(options) == 2  # picker instead of a coin flip
    assert any("laptop" in title for _cid, title in options)


async def test_list_open_work_on_demand() -> None:
    _store, service = await _two_open_drafts()
    service.gateway.turns.append(_list_turn())  # type: ignore[attr-defined]
    outcome = await service.handle_message(
        channel_key="zalo:1", text="đang dở những gì thế?", context=CONTEXT, display_name="An"
    )
    assert "2 việc chưa xong" in outcome.replies[0].text


async def test_pick_draft_by_number_resumes_it() -> None:
    store, service = await _two_open_drafts()
    laptop = _by_item(store, "laptop")
    outcome = await service.handle_pick_case(conversation_id=laptop.id, context=CONTEXT)
    assert store.conversations[laptop.id].state == "collecting"
    assert any("laptop" in reply.text for reply in outcome.replies)


async def test_pivot_back_to_a_parked_item_continues_it() -> None:
    """Even read as a NEW request, a known item must not start from scratch."""
    store, service = await _two_open_drafts()
    back_to_laptop = IntakeChatTurn(
        intent="create_request",
        slots=IntakeSlots(item_summary="laptop cho nhân viên", estimated_value_vnd=7_500_000_000),
        reply_vi="Mình ghi nhận ngân sách nhé.",
        reasoning_summary="",
    )
    service.gateway.turns.append(back_to_laptop)  # type: ignore[attr-defined]
    await service.handle_message(
        channel_key="zalo:1",
        text="giờ mua laptop tiếp, ngân sách 7,5 tỷ",
        context=CONTEXT,
        display_name="An",
    )
    laptop = _by_item(store, "laptop")
    assert laptop.state in ("collecting", "confirming")
    assert laptop.slots.quantity == 500  # earlier slots survived
    assert laptop.slots.estimated_value_vnd == 7_500_000_000  # new one merged in
    assert len([c for c in store.conversations.values() if c.state != "parked"]) == 1


async def test_cancel_resumes_parked_draft() -> None:
    store = FakeStore()
    cancel_turn = IntakeChatTurn(
        intent="cancel", slots=IntakeSlots(), reply_vi="Đã huỷ.", reasoning_summary=""
    )
    gw = SequenceGateway(
        turn=cancel_turn,
        turns=[_laptop_partial(), _pivot_to_chairs(), cancel_turn],
    )
    service = make_service(store, cancel_turn, gateway=gw)
    await service.handle_message(
        channel_key="zalo:1", text="mua laptop", context=CONTEXT, display_name="An"
    )
    await service.handle_message(
        channel_key="zalo:1", text="thôi, mua ghế", context=CONTEXT, display_name="An"
    )
    outcome = await service.handle_message(
        channel_key="zalo:1", text="thôi huỷ vụ ghế đi", context=CONTEXT, display_name="An"
    )
    resumed = next(
        c for c in store.conversations.values() if c.slots.item_summary == "laptop cho nhân viên"
    )
    assert resumed.state == "collecting"  # parked draft is live again
    assert any("Quay lại hồ sơ" in r.text for r in outcome.replies)
