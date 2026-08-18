"""What actually happened, and the only thing allowed to describe it.

A chat turn used to classify the intent and write the reply in one model call.
The reply therefore described an intention, not an outcome — so a request to
extend a bid deadline was answered "addendum sẽ được lập và trình CP3" while
the case never moved and no artifact appeared. Nobody lied; the sentence was
simply written before anything was attempted.

So the order changes. The action runs; what changed is OBSERVED by comparing
the case before and after; only then is there something to say. ``done`` is
unreachable without an after-snapshot — it cannot be asserted from an intent.

This module holds no policy. Who may act, from which state, and which
checkpoint applies belong to the rule pack, the approval matrix and the case
state machine, and are read from there. What an action is called lives in the
action registry. Here there is only: observe, then describe.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Literal

from dw_tender.application.conversation.actions import spec_for

Outcome = Literal["done", "refused", "not_attempted"]


@dataclass(frozen=True, slots=True)
class CaseSnapshot:
    """The observable facts about a case at one instant.

    Notifications count as an effect. A requester proposing an addendum moves
    no state and writes no artifact by design — procurement files the paperwork
    — but a decision card does go out, and reporting that as "nothing happened"
    would be as wrong as the promise it replaced.
    """

    state: str
    artifact_types: frozenset[str] = frozenset()
    notification_count: int = 0
    title: str = ""
    case_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class ActionReceipt:
    """The observed result of one attempted action."""

    action: str
    outcome: Outcome
    case_title: str = ""
    case_id: uuid.UUID | None = None
    previous_state: str = ""
    new_state: str = ""
    artifacts_created: tuple[str, ...] = ()
    notifications_sent: int = 0
    # Why it did not happen. Shown to the person, so it names the obstacle.
    reason: str = ""
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.outcome == "done"

    @property
    def changed_state(self) -> bool:
        return bool(self.new_state) and self.new_state != self.previous_state

    @property
    def had_effect(self) -> bool:
        """Did anything observable happen at all?"""
        return bool(self.changed_state or self.artifacts_created or self.notifications_sent)


def observed(
    action: str,
    before: CaseSnapshot | None,
    after: CaseSnapshot | None,
    error: Exception | None = None,
    warnings: tuple[str, ...] = (),
) -> ActionReceipt:
    """Build a receipt from measurements, not from what was intended.

    ``after`` is the proof of execution: without it the outcome cannot be
    ``done``, however confidently the caller believes the handler ran.
    """
    prev = before.state if before else ""
    title = (after.title if after else "") or (before.title if before else "")
    case_id = (after.case_id if after else None) or (before.case_id if before else None)

    if error is not None:
        return ActionReceipt(
            action=action,
            outcome="refused",
            case_title=title,
            case_id=case_id,
            previous_state=prev,
            reason=str(error),
            warnings=warnings,
        )
    if after is None:
        return ActionReceipt(
            action=action,
            outcome="not_attempted",
            case_title=title,
            case_id=case_id,
            previous_state=prev,
            warnings=warnings,
        )
    fresh = after.artifact_types - (before.artifact_types if before else frozenset())
    notified = max(0, after.notification_count - (before.notification_count if before else 0))
    return ActionReceipt(
        action=action,
        outcome="done",
        case_title=title,
        case_id=case_id,
        previous_state=prev,
        new_state=after.state,
        artifacts_created=tuple(sorted(fresh)),
        notifications_sent=notified,
        warnings=warnings,
    )


def describe(receipt: ActionReceipt, state_label: dict[str, str] | None = None) -> str:
    """The deterministic sentence for a receipt.

    Built from the recorded delta, so it cannot describe a change that did not
    occur. A model may later smooth the wording; it may not add facts.
    """
    labels = state_label or {}

    def state(name: str) -> str:
        return labels.get(name, name)

    verb = spec_for(receipt.action).label
    case = f" — hồ sơ «{receipt.case_title}»" if receipt.case_title else ""

    if receipt.outcome == "not_attempted":
        tail = f": {receipt.reason}" if receipt.reason else "."
        return f"Mình chưa {verb} được{case}{tail}"
    if receipt.outcome == "refused":
        tail = f" Hồ sơ vẫn đang {state(receipt.previous_state)}." if receipt.previous_state else ""
        return f"⚠️ Không {verb} được{case}: {receipt.reason}{tail}"

    if not receipt.had_effect:
        # The handler ran without complaint but nothing moved. Saying "đã xong"
        # here is the failure this module exists to prevent.
        return f"Mình chưa thấy thay đổi nào sau khi {verb}{case}. Bạn kiểm tra lại giúp mình nhé."

    lines = [f"✅ Đã {verb}{case}."]
    if receipt.changed_state:
        lines.append(f"Trạng thái: {state(receipt.previous_state)} → {state(receipt.new_state)}.")
    if receipt.artifacts_created:
        lines.append("Đã lập: " + ", ".join(receipt.artifacts_created) + ".")
    if receipt.notifications_sent and not receipt.artifacts_created:
        lines.append("Đã báo người phụ trách xử lý tiếp.")
    lines.extend(f"Lưu ý: {w}" for w in receipt.warnings)
    return "\n".join(lines)


def reply_for(
    intent: str,
    model_reply: str,
    receipt: ActionReceipt | None,
    state_label: dict[str, str] | None = None,
) -> str:
    """Which sentence the person is allowed to receive.

    The model's own wording survives only for intents that assert nothing — a
    question, a greeting, a slot being collected. The moment an intent claims a
    change, the sentence comes from the receipt, or says plainly that nothing
    was done.
    """
    if not spec_for(intent).mutates:
        return model_reply
    if receipt is None:
        verb = spec_for(intent).label
        return (
            f"Mình chưa {verb} được — chưa xác định được hồ sơ nào để thực hiện. "
            "Bạn nói rõ hồ sơ giúp mình nhé."
        )
    return describe(receipt, state_label)
