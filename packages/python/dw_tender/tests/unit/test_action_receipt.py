"""A sentence that claims a change must come from an observed change.

The bug these pin: a request to extend a bid deadline was answered "addendum
sẽ được lập và trình CP3" while the case never moved and no artifact appeared.
The reply had been written at classification time, before anything was tried.

Two guarantees are enforced here. A reply about a mutating intent is built
only from a receipt; and a receipt can only say ``done`` when there is an
after-snapshot to prove it.
"""

from __future__ import annotations

import typing
import uuid

import pytest

from dw_kernel.errors import ConflictError
from dw_tender.application.conversation.actions import ACTIONS, mutating_intents, spec_for
from dw_tender.application.conversation.receipt import (
    CaseSnapshot,
    describe,
    observed,
    reply_for,
)
from dw_tender.application.conversation.schemas import ChatIntent

pytestmark = pytest.mark.unit

STATES = {
    "published": "đã phát hành, chờ nhà cung cấp nộp",
    "cp3_pending": "chờ duyệt CP3 (addendum)",
    "receiving_bids": "đang nhận hồ sơ dự thầu",
    "cp4_ready": "chờ xác nhận mở thầu (CP4)",
}

# The exact sentence the system produced while doing nothing.
LIE = "Mình đã chuyển đề nghị… addendum sẽ được lập và trình CP3."

CASE = uuid.uuid4()


def _before(state: str = "published", artifacts: tuple[str, ...] = ()) -> CaseSnapshot:
    return CaseSnapshot(
        state=state,
        artifact_types=frozenset(artifacts),
        title="Mua 200 màn hình cho team AI FDX",
        case_id=CASE,
    )


def _after(state: str, artifacts: tuple[str, ...] = ()) -> CaseSnapshot:
    return CaseSnapshot(
        state=state,
        artifact_types=frozenset(artifacts),
        title="Mua 200 màn hình cho team AI FDX",
        case_id=CASE,
    )


# ------------------------------------------------ one owner for the metadata --
def test_every_intent_has_exactly_one_spec() -> None:
    """The Literal owns the set; the registry owns the metadata; neither drifts."""
    declared = set(typing.get_args(ChatIntent))
    registered = set(ACTIONS)
    assert declared - registered == set(), "intent without a spec"
    # The registry may carry procurement-side actions that are not chat intents.
    assert registered - declared == {"draft_addendum"}


def test_the_mutating_set_is_derived_not_restated() -> None:
    assert mutating_intents() == {
        "confirm_request",
        "amend_request",
        "request_addendum",
        "record_submission",
        "open_bids",
        "draft_addendum",
    }


def test_an_unregistered_intent_is_treated_as_mutating() -> None:
    """Fail closed: an unknown action might change something."""
    assert spec_for("some_future_action").mutates is True


# ------------------------------------------------- done must be observed --
def test_done_is_impossible_without_an_after_snapshot() -> None:
    receipt = observed("request_addendum", _before(), after=None)
    assert receipt.outcome == "not_attempted"
    assert not receipt.ok
    assert receipt.new_state == ""


def test_a_raised_error_becomes_a_refusal_carrying_its_reason() -> None:
    error = ConflictError("hồ sơ đã qua giai đoạn nhận sửa đổi")
    receipt = observed("request_addendum", _before(), _after("published"), error=error)
    assert receipt.outcome == "refused"
    assert "đã qua giai đoạn nhận sửa đổi" in receipt.reason
    assert receipt.previous_state == "published"


def test_artifacts_created_are_the_diff_not_the_whole_list() -> None:
    receipt = observed(
        "request_addendum",
        _before(artifacts=("solicitation_package", "publication_record")),
        _after("cp3_pending", ("solicitation_package", "publication_record", "addendum_draft")),
    )
    assert receipt.artifacts_created == ("addendum_draft",)
    assert receipt.changed_state


def test_a_handler_that_changes_nothing_still_reports_done_but_no_transition() -> None:
    receipt = observed("record_submission", _before("receiving_bids"), _after("receiving_bids"))
    assert receipt.ok
    assert not receipt.changed_state


# ---------------------------------------------------------------- the bug --
def test_no_receipt_means_no_claim() -> None:
    """Nothing ran, so the model's promise must not reach the person."""
    out = reply_for("request_addendum", LIE, None, STATES)
    assert out != LIE
    assert "sẽ được lập" not in out
    assert "chưa" in out.lower()


def test_a_refusal_reaches_the_person_as_a_refusal() -> None:
    error = ConflictError("hồ sơ đã qua giai đoạn nhận sửa đổi")
    receipt = observed("request_addendum", _before(), _after("published"), error=error)
    out = reply_for("request_addendum", LIE, receipt, STATES)
    assert "Không ghi nhận đề nghị sửa đổi được" in out
    assert "đã phát hành, chờ nhà cung cấp nộp" in out, "says where the case still is"
    assert "sẽ được lập" not in out


def test_a_real_change_is_described_from_the_delta() -> None:
    receipt = observed("request_addendum", _before(), _after("cp3_pending", ("addendum_draft",)))
    out = reply_for("request_addendum", LIE, receipt, STATES)
    assert out.startswith("✅ Đã ghi nhận đề nghị sửa đổi")
    assert "đã phát hành, chờ nhà cung cấp nộp → chờ duyệt CP3 (addendum)" in out
    assert "addendum_draft" in out


# ------------------------------------------------------- what stays human --
def test_intents_that_claim_nothing_keep_the_model_wording() -> None:
    """Collecting a slot or answering a question is not an assertion."""
    for intent in ("provide_info", "ask_status", "ask_knowledge", "list_cases", "other"):
        assert reply_for(intent, "câu trả lời tự nhiên", None) == "câu trả lời tự nhiên"


# ------------------------------------------------------------- rendering --
def test_warnings_ride_along_without_changing_the_verdict() -> None:
    receipt = observed(
        "open_bids",
        _before("receiving_bids"),
        _after("cp4_ready"),
        warnings=("chỉ 1/3 nhà cung cấp tối thiểu",),
    )
    out = describe(receipt, STATES)
    assert out.startswith("✅")
    assert "chỉ 1/3 nhà cung cấp tối thiểu" in out


def test_unknown_state_names_fall_back_to_the_raw_value() -> None:
    """A label table must never swallow a state it has not heard of."""
    receipt = observed("request_addendum", _before("brand_new"), _after("another_new"))
    assert "brand_new → another_new" in describe(receipt, STATES)
