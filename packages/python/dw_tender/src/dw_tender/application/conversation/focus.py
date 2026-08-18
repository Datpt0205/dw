"""Which case the person means — decided from data, or asked about.

An approver typed "kéo dài thời gian 10 ngày mời thầu". Nothing in her chat
history owned a case, because she had never filed one, so the message fell
through to intake and came back asking what she wanted to buy. The candidates
were being drawn from the wrong place: whose conversation it is, rather than
which cases the person can see.

So the menu is built from cases, for every role, and the model never names a
case — it points at a row number that code assigned. Two rules keep that
honest. A row it invented resolves to nothing. And the certainty required
rises with what the action costs: reading the only open case is fine, signing
it because it happens to be the only one is not.

Pure functions over plain data: no I/O, no model, no state machine. Whether an
action is *allowed* from a given state stays with the handler that enforces
it — a candidate here is one the person might mean, not one they may act on.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from dw_tender.application.conversation.actions import Risk
from dw_tender.application.conversation.service import rank_by_label

Relation = Literal["FOCUS", "ACTIONABLE", "RELATED", "RECENT", "PENDING_INPUT"]

# States where a case is waiting on a person rather than on the clock or a
# supplier. Used only to tag a candidate as worth surfacing first; refusing an
# action from the wrong state remains the handler's job.
_AWAITING_A_HUMAN: frozenset[str] = frozenset(
    {"draft", "cp1_pending", "cp2_pending", "cp3_pending", "cp4_ready"}
)


@dataclass(frozen=True, slots=True)
class CaseFact:
    """A filed case, as the broker needs to see it."""

    case_id: uuid.UUID
    title: str
    owner_name: str
    state: str
    created_by: uuid.UUID


@dataclass(frozen=True, slots=True)
class DraftFact:
    """A request still being typed, not yet a case."""

    conversation_id: uuid.UUID
    label: str
    status: str = ""


@dataclass(frozen=True, slots=True)
class Candidate:
    ref: int
    title: str
    state: str
    relations: tuple[Relation, ...]
    case_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None
    owner_name: str = ""

    def describe(self) -> str:
        who = f" — {self.owner_name} đề nghị" if self.owner_name else ""
        where = f" ({self.state})" if self.state else ""
        return f"{self.ref}. {self.title}{where}{who}"


@dataclass(frozen=True, slots=True)
class Resolution:
    kind: Literal["resolved", "ambiguous", "no_target"]
    candidate: Candidate | None = None
    options: tuple[Candidate, ...] = ()


def build_menu(
    *,
    cases: list[CaseFact],
    drafts: list[DraftFact],
    actor_id: uuid.UUID,
    can_decide: bool,
    focus_case_id: uuid.UUID | None = None,
) -> tuple[Candidate, ...]:
    """Everything this person could plausibly be talking about, numbered.

    Visibility is the same rule the portfolio answer uses: someone who decides
    approvals sees the workspace, everyone else sees what they filed. Note that
    it is deliberately wider than "things you may act on" — a head of
    procurement asking where someone else's case stands is a fair question.
    """
    visible = [c for c in cases if can_decide or c.created_by == actor_id]

    def rank(case: CaseFact) -> int:
        if case.case_id == focus_case_id:
            return 0
        return 1 if case.state in _AWAITING_A_HUMAN else 2

    ordered = sorted(visible, key=rank)
    out: list[Candidate] = []
    for case in ordered:
        relations: list[Relation] = []
        if case.case_id == focus_case_id:
            relations.append("FOCUS")
        if case.state in _AWAITING_A_HUMAN:
            relations.append("ACTIONABLE")
        else:
            relations.append("RELATED")
        out.append(
            Candidate(
                ref=len(out) + 1,
                title=case.title,
                state=case.state,
                relations=tuple(relations),
                case_id=case.case_id,
                owner_name=case.owner_name,
            )
        )
    for draft in drafts:
        out.append(
            Candidate(
                ref=len(out) + 1,
                title=draft.label,
                state=draft.status,
                relations=("PENDING_INPUT",),
                conversation_id=draft.conversation_id,
            )
        )
    return tuple(out)


def resolve(
    *,
    menu: tuple[Candidate, ...],
    target_ref: int | None,
    text: str,
    risk: Risk,
) -> Resolution:
    """Pick the candidate, or say plainly that it cannot be picked."""
    if not menu:
        return Resolution(kind="no_target")

    by_ref = {c.ref: c for c in menu}
    if target_ref is not None:
        chosen = by_ref.get(target_ref)
        # A ref outside the menu means the model invented one. Clamping it to
        # the nearest row would turn a hallucination into an action.
        return (
            Resolution(kind="resolved", candidate=chosen)
            if chosen is not None
            else Resolution(kind="ambiguous", options=menu)
        )

    named = _named_in(text, menu)
    if named is not None:
        return Resolution(kind="resolved", candidate=named)

    # Nothing named. What may be inferred depends on the cost of being wrong.
    if risk == "approve":
        # Signing is not undoable, so "the only one" is never good enough.
        return Resolution(kind="ambiguous", options=menu)
    if len(menu) == 1:
        return Resolution(kind="resolved", candidate=menu[0])
    if risk in ("read", "draft"):
        focus = [c for c in menu if "FOCUS" in c.relations]
        if len(focus) == 1:
            return Resolution(kind="resolved", candidate=focus[0])
    return Resolution(kind="ambiguous", options=menu)


def _named_in(text: str, menu: tuple[Candidate, ...]) -> Candidate | None:
    """The candidate the message actually names, by title or by requester."""
    labels = [f"{c.title} {c.owner_name}".strip() for c in menu]
    scores = rank_by_label(text, labels)
    best = max(scores, default=0.0)
    if best <= 0 or scores.count(best) > 1:
        return None
    return menu[scores.index(best)]


def render(menu: tuple[Candidate, ...], limit: int = 6) -> str:
    return "\n".join(c.describe() for c in menu[:limit])
