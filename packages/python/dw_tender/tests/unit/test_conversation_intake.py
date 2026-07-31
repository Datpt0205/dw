"""Chat intake: slot merge, deterministic completeness, confirm-before-commit."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

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
    methods=(
        Method("direct_purchase", "Mua trực tiếp", 100_000_000, 1),
        Method("rfq", "Chào giá", 1_000_000_000, 3),
        Method("open_tender", "Đấu thầu", None, 3),
    ),
    weighted_total_must_equal=100,
    require_mandatory_criteria=True,
    legal_review_required_above=500_000_000,
    finance_review_required_above=500_000_000,
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
    title="Mua 100 laptop",
    item_summary="laptop cho developer",
    quantity=100,
    estimated_value_vnd=2_000_000_000,
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

    async def generate_structured(self, request, output_type, *, run_context):
        return self.turn


@dataclass
class FakeCreateCase:
    created: list[object] = field(default_factory=list)

    async def handle(self, command, context) -> uuid.UUID:
        self.created.append(command)
        return uuid.uuid4()


def make_service(
    store: FakeStore, turn: IntakeChatTurn, create_case: FakeCreateCase | None = None
) -> ConversationIntakeService:
    return ConversationIntakeService(
        store=store,
        gateway=FakeGateway(turn),  # type: ignore[arg-type]
        create_case=create_case or FakeCreateCase(),  # type: ignore[arg-type]
        rules=RULES,
        clock=FakeClock(),  # type: ignore[arg-type]
        id_generator=FakeIdGen(),  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------- schemas ----
def test_merge_keeps_existing_and_overrides_with_new() -> None:
    base = IntakeSlots(quantity=100, delivery_location="Hà Nội")
    update = IntakeSlots(quantity=120, estimated_value_vnd=2_000_000_000)
    merged = base.merged_with(update)
    assert merged.quantity == 120
    assert merged.delivery_location == "Hà Nội"
    assert merged.estimated_value_vnd == 2_000_000_000


def test_missing_required_uses_rule_pack_supplier_minimum() -> None:
    slots = FULL_SLOTS.model_copy(update={"supplier_names": ["FPT"]})
    missing = missing_required(slots, RULES)
    assert any("tối thiểu 3" in item for item in missing)

    # Small direct purchase only needs 1 supplier.
    small = slots.model_copy(update={"estimated_value_vnd": 50_000_000})
    assert missing_required(small, RULES) == []


def test_missing_required_empty_when_complete() -> None:
    assert missing_required(FULL_SLOTS, RULES) == []


def test_render_pr_markdown_contains_key_facts() -> None:
    text = render_pr_markdown(FULL_SLOTS, requester="Nguyễn Văn An", pr_ref="SLACK-1")
    assert "2.000.000.000 VND" in text
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
    replies = await make_service(store, turn).handle_message(
        channel_key="slack:D1", text="Tôi muốn mua 100 laptop", context=CONTEXT, display_name="An"
    )
    assert len(replies) == 1 and replies[0].kind == "message"
    assert "ngân sách" in replies[0].text
    conv = next(iter(store.conversations.values()))
    assert conv.state == "collecting"
    assert conv.slots.quantity == 100


async def test_complete_message_returns_confirm_card() -> None:
    store = FakeStore()
    turn = IntakeChatTurn(
        intent="provide_info", slots=FULL_SLOTS, reply_vi="Đã đủ thông tin.", reasoning_summary=""
    )
    replies = await make_service(store, turn).handle_message(
        channel_key="slack:D1", text="đủ hết rồi", context=CONTEXT, display_name="An"
    )
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

    replies = await service.handle_action(
        action="confirm", conversation_id=conv_id, context=CONTEXT, display_name="An"
    )
    assert replies[0].kind == "case_link"
    assert len(create_case.created) == 1
    command = create_case.created[0]
    assert command.estimated_value_minor == 2_000_000_000
    assert command.supplier_names == ("FPT", "CMC", "Viettel")
    assert command.deadline == "45 ngày"
    assert "laptop" in command.pr_text

    # Double click: no second case, still returns the link.
    again = await service.handle_action(
        action="confirm", conversation_id=conv_id, context=CONTEXT, display_name="An"
    )
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
    replies = await service.handle_action(
        action="edit", conversation_id=conv_id, context=CONTEXT, display_name="An"
    )
    assert store.conversations[conv_id].state == "collecting"
    assert "sửa" in replies[0].text.lower()


async def test_cancel_intent_closes_conversation() -> None:
    store = FakeStore()
    turn = IntakeChatTurn(
        intent="cancel", slots=IntakeSlots(), reply_vi="Đã huỷ.", reasoning_summary=""
    )
    await make_service(store, turn).handle_message(
        channel_key="slack:D1", text="thôi huỷ đi", context=CONTEXT, display_name="An"
    )
    conv = next(iter(store.conversations.values()))
    assert conv.state == "cancelled"


def test_chat_reply_defaults() -> None:
    reply = ChatReply(text="hi")
    assert reply.kind == "message" and reply.summary_lines == ()
