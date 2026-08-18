"""Which case is "this one" — and when the honest answer is to ask.

The bug this exists for: an approver typed "kéo dài thời gian 10 ngày mời
thầu" and the system, finding no conversation of hers that owned a case,
read it as a brand-new purchase request and asked what she wanted to buy.

The person asking is usually not the person who filed it, so the candidates
cannot come from her chat history. They come from the cases she can see. And
when several fit, asking is the correct outcome, not a failure.
"""

from __future__ import annotations

import uuid

from dw_tender.application.conversation.focus import (
    CaseFact,
    DraftFact,
    build_menu,
    resolve,
)

AN = uuid.uuid4()
CHI = uuid.uuid4()

MONITORS = uuid.uuid4()
LAPTOPS = uuid.uuid4()
MAINTENANCE = uuid.uuid4()


HA = uuid.uuid4()


def _case(
    case_id: uuid.UUID,
    title: str,
    state: str,
    owner: str = "Nguyễn Văn An",
    filed_by: uuid.UUID | None = None,
) -> CaseFact:
    # owner_name is the display name on the card; created_by is who filed it,
    # and only the second one governs visibility.
    return CaseFact(
        case_id=case_id,
        title=title,
        owner_name=owner,
        state=state,
        created_by=filed_by or AN,
    )


PUBLISHED_THREE = [
    _case(MONITORS, "Mua 200 màn hình cho team AI FDX", "published"),
    _case(LAPTOPS, "Mua 50 laptop cho phòng AI", "published"),
    _case(MAINTENANCE, "Thuê dịch vụ bảo trì điện 2026", "cp2_pending", "Lê Thu Hà", HA),
]


# ============================ THE BUG, AS AN ACCEPTANCE TEST ================
def test_approver_asking_vaguely_gets_a_question_not_a_new_request() -> None:
    """Chi: "kéo dài thời gian 10 ngày mời thầu" — three cases could be meant."""
    menu = build_menu(cases=PUBLISHED_THREE, drafts=[], actor_id=CHI, can_decide=True)
    assert len(menu) == 3, "an approver sees cases she never filed"

    outcome = resolve(
        menu=menu, target_ref=None, text="kéo dài thời gian 10 ngày mời thầu", risk="mutate"
    )
    assert outcome.kind == "ambiguous"
    assert outcome.candidate is None
    assert len(outcome.options) == 3


def test_naming_it_resolves_the_same_message() -> None:
    menu = build_menu(cases=PUBLISHED_THREE, drafts=[], actor_id=CHI, can_decide=True)
    outcome = resolve(
        menu=menu, target_ref=None, text="kéo dài 10 ngày cho vụ laptop", risk="mutate"
    )
    assert outcome.kind == "resolved"
    assert outcome.candidate is not None
    assert outcome.candidate.case_id == LAPTOPS


# ================================== the menu ================================
def test_a_requester_only_sees_their_own_cases() -> None:
    menu = build_menu(cases=PUBLISHED_THREE, drafts=[], actor_id=AN, can_decide=False)
    assert {c.case_id for c in menu} == {MONITORS, LAPTOPS}, "Hà's case is not An's business"


def test_the_focus_case_is_marked_and_comes_first() -> None:
    menu = build_menu(
        cases=PUBLISHED_THREE, drafts=[], actor_id=CHI, can_decide=True, focus_case_id=LAPTOPS
    )
    assert menu[0].case_id == LAPTOPS
    assert "FOCUS" in menu[0].relations


def test_a_case_awaiting_this_person_is_actionable() -> None:
    menu = build_menu(cases=PUBLISHED_THREE, drafts=[], actor_id=CHI, can_decide=True)
    waiting = next(c for c in menu if c.case_id == MAINTENANCE)
    assert "ACTIONABLE" in waiting.relations
    running = next(c for c in menu if c.case_id == MONITORS)
    assert "ACTIONABLE" not in running.relations
    assert "RELATED" in running.relations


def test_drafts_appear_alongside_filed_cases() -> None:
    draft = DraftFact(conversation_id=uuid.uuid4(), label="40 bàn phím cơ", status="đang khai dở")
    menu = build_menu(cases=PUBLISHED_THREE, drafts=[draft], actor_id=AN, can_decide=False)
    entry = next(c for c in menu if c.case_id is None)
    assert entry.title == "40 bàn phím cơ"
    assert "PENDING_INPUT" in entry.relations


def test_refs_are_one_based_and_contiguous() -> None:
    """The model points at a number, so the numbers must be trivially valid."""
    menu = build_menu(cases=PUBLISHED_THREE, drafts=[], actor_id=CHI, can_decide=True)
    assert [c.ref for c in menu] == [1, 2, 3]


# ================================ resolution ================================
def test_a_valid_ref_from_the_model_wins() -> None:
    menu = build_menu(cases=PUBLISHED_THREE, drafts=[], actor_id=CHI, can_decide=True)
    outcome = resolve(menu=menu, target_ref=2, text="cái này", risk="mutate")
    assert outcome.kind == "resolved"
    assert outcome.candidate is not None
    assert outcome.candidate.ref == 2


def test_an_invented_ref_is_refused_not_clamped() -> None:
    """A model pointing at row 9 of a 3-row menu has not chosen anything."""
    menu = build_menu(cases=PUBLISHED_THREE, drafts=[], actor_id=CHI, can_decide=True)
    outcome = resolve(menu=menu, target_ref=9, text="", risk="read")
    assert outcome.kind == "ambiguous"
    assert outcome.candidate is None


def test_pointing_by_requester_name_works() -> None:
    menu = build_menu(cases=PUBLISHED_THREE, drafts=[], actor_id=CHI, can_decide=True)
    outcome = resolve(menu=menu, target_ref=None, text="hồ sơ do Lê Thu Hà yêu cầu", risk="mutate")
    assert outcome.kind == "resolved"
    assert outcome.candidate is not None
    assert outcome.candidate.case_id == MAINTENANCE


def test_an_empty_menu_is_no_target_not_ambiguous() -> None:
    outcome = resolve(menu=(), target_ref=None, text="gia hạn thêm 7 ngày", risk="mutate")
    assert outcome.kind == "no_target"
    assert outcome.options == ()


# ============================ risk raises the bar ===========================
def test_the_only_case_resolves_for_reading_and_for_changing() -> None:
    menu = build_menu(cases=PUBLISHED_THREE[:1], drafts=[], actor_id=CHI, can_decide=True)
    for risk in ("read", "draft", "mutate"):
        outcome = resolve(menu=menu, target_ref=None, text="cái này sao rồi", risk=risk)
        assert outcome.kind == "resolved", risk


def test_but_approving_never_infers_from_being_the_only_one() -> None:
    """Signing is not undoable; "the only one" is not the same as "this one"."""
    menu = build_menu(cases=PUBLISHED_THREE[:1], drafts=[], actor_id=CHI, can_decide=True)
    outcome = resolve(menu=menu, target_ref=None, text="chốt sổ đi", risk="approve")
    assert outcome.kind == "ambiguous"


def test_approving_resolves_when_the_case_is_actually_named() -> None:
    menu = build_menu(cases=PUBLISHED_THREE[:1], drafts=[], actor_id=CHI, can_decide=True)
    outcome = resolve(
        menu=menu, target_ref=None, text="chốt sổ hồ sơ màn hình team AI FDX", risk="approve"
    )
    assert outcome.kind == "resolved"


def test_focus_carries_a_draft_action_but_not_a_mutating_one() -> None:
    """Working on a case makes "it" mean that case — up to a point."""
    menu = build_menu(
        cases=PUBLISHED_THREE, drafts=[], actor_id=CHI, can_decide=True, focus_case_id=MONITORS
    )
    assert resolve(menu=menu, target_ref=None, text="xem lại đi", risk="draft").kind == "resolved"
    assert resolve(menu=menu, target_ref=None, text="gia hạn 7 ngày", risk="mutate").kind == (
        "ambiguous"
    ), "three cases could be meant; being on screen is not being named"
