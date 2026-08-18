"""The one place chat actions are described.

``ChatIntent`` owns the SET of intents — it has to stay a static Literal
because it is the model's structured-output schema. What it cannot carry is
metadata, so that used to get restated wherever it was needed: one module
listing which intents mutate, another spelling their verb phrases, a third
holding channel action ids. Three lists, three chances to disagree.

This registry owns the metadata, keyed by the intent names ``ChatIntent``
already defines. A test binds the two: every intent has a spec, every spec
names a real intent. Adding an intent without deciding whether a reply about
it asserts a change is then a red test, not a silent default.

Deliberately absent: who may perform an action, and from which state. Those
are policy, and they already have owners — the rule pack, the approval matrix,
and the case state machine. Nothing here may duplicate them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# How wrong it is to act on the wrong case. Reading someone else's status is a
# nuisance; approving the wrong package is not undoable. The target resolver
# demands more certainty as this rises — see ``focus.resolve``.
Risk = Literal["read", "draft", "mutate", "approve"]


@dataclass(frozen=True, slots=True)
class ActionSpec:
    """What a chat intent is, for the purpose of talking about it."""

    intent: str
    # Verb phrase used to describe the attempt: "Đã {label}", "Không {label} được".
    label: str
    # True when a reply about this intent asserts that the world changed. Such a
    # sentence may only be built from an observed result, never at classification
    # time — see ``receipt.reply_for``.
    mutates: bool
    risk: Risk = "read"
    # Which application handler carries it out. Documentation, not dispatch:
    # the router still decides, this only makes the pairing findable.
    handler: str = ""


def _spec(
    intent: str,
    label: str,
    *,
    mutates: bool = False,
    risk: Risk = "read",
    handler: str = "",
) -> ActionSpec:
    return ActionSpec(intent=intent, label=label, mutates=mutates, risk=risk, handler=handler)


ACTIONS: dict[str, ActionSpec] = {
    # --- collecting a request: nothing outside the draft changes yet --------
    "create_request": _spec("create_request", "mở yêu cầu mua sắm mới"),
    "provide_info": _spec("provide_info", "ghi nhận thông tin"),
    "edit_request": _spec("edit_request", "mở lại phần khai để sửa"),
    "cancel": _spec("cancel", "huỷ yêu cầu đang khai"),
    # --- juggling several requests -----------------------------------------
    "switch_request": _spec("switch_request", "chuyển sang yêu cầu khác"),
    "list_requests": _spec("list_requests", "liệt kê việc đang dở"),
    "list_cases": _spec("list_cases", "liệt kê hồ sơ"),
    # --- questions: read-only ----------------------------------------------
    "ask_status": _spec("ask_status", "tra trạng thái hồ sơ"),
    "ask_knowledge": _spec("ask_knowledge", "tra kho tài liệu"),
    "check_readiness": _spec("check_readiness", "rà soát bộ hồ sơ"),
    "other": _spec("other", "trả lời"),
    # --- the ones that change something ------------------------------------
    "confirm_request": _spec(
        "confirm_request",
        "tạo hồ sơ",
        mutates=True,
        risk="mutate",
        handler="CreatePreparationCaseHandler",
    ),
    "amend_request": _spec(
        "amend_request",
        "sửa hồ sơ",
        mutates=True,
        risk="mutate",
        handler="AmendPreparationCaseHandler",
    ),
    "request_addendum": _spec(
        "request_addendum",
        "ghi nhận đề nghị sửa đổi",
        mutates=True,
        risk="mutate",
        handler="ProposePreparationAddendumHandler",
    ),
    "record_submission": _spec(
        "record_submission",
        "ghi nhận hồ sơ dự thầu",
        mutates=True,
        risk="mutate",
        handler="RecordPreparationSubmissionHandler",
    ),
    "open_bids": _spec(
        "open_bids",
        "chốt sổ tiếp nhận",
        mutates=True,
        # Closing the register decides which bids are in the running at all.
        risk="approve",
        handler="RequestCp4Handler",
    ),
}

# Actions taken by procurement rather than proposed by the requester. Same
# verb table, so the sentence stays consistent whoever performed it.
ACTIONS["draft_addendum"] = _spec(
    "draft_addendum",
    "lập bản sửa đổi",
    mutates=True,
    risk="mutate",
    handler="SubmitPreparationAddendumHandler",
)


def spec_for(intent: str) -> ActionSpec:
    """Never raises: an unregistered intent is described, not crashed on.

    A missing spec is a bug the binding test catches at build time; at runtime
    the safe reading is "this might change something", so it is treated as
    mutating and its reply has to come from a receipt like any other.
    """
    known = ACTIONS.get(intent)
    if known is not None:
        return known
    return ActionSpec(intent=intent, label=intent.replace("_", " "), mutates=True)


def mutating_intents() -> frozenset[str]:
    return frozenset(name for name, spec in ACTIONS.items() if spec.mutates)
