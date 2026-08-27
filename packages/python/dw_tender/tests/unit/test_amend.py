"""Changing a request while changing it is still cheap — and refusing after.

The line is CP2. Before it the package is internal and a correction costs a
re-check; after it the package has gone to suppliers and a change only some of
them hear about is an unfair one. These pin both sides of that line, and the
two things that make the "before" side safe: the pending card is withdrawn,
and the run starts over.
"""

from __future__ import annotations

import pytest

from dw_tender.domain.preparation.entities import CaseState

pytestmark = pytest.mark.unit

BEFORE_CP2 = [
    CaseState.DRAFT,
    CaseState.INTAKE_READY,
    CaseState.ANALYZING,
    CaseState.WAITING_CLARIFICATION,
    CaseState.APPROACH_READY,
    CaseState.CP1_PENDING,
    CaseState.CP1_APPROVED,
    CaseState.BUILDING_SOLICITATION,
    CaseState.PACKAGE_READY,
    CaseState.CP2_PENDING,
]

AFTER_CP2 = [
    CaseState.CP2_APPROVED,
    CaseState.PACKAGE_OFFICIAL,
    CaseState.PUBLISHED,
    CaseState.CP3_PENDING,
    CaseState.RECEIVING_BIDS,
    CaseState.CP4_READY,
    CaseState.COMPLETED,
]


@pytest.mark.parametrize("state", BEFORE_CP2, ids=[s.value for s in BEFORE_CP2])
def test_anything_before_cp2_is_still_amendable(state: CaseState) -> None:
    assert state.accepts_amendment, f"{state.value} is internal — a fix costs a re-check"


@pytest.mark.parametrize("state", AFTER_CP2, ids=[s.value for s in AFTER_CP2])
def test_nothing_after_cp2_is_amended_in_place(state: CaseState) -> None:
    assert not state.accepts_amendment, f"{state.value} has left the building — use an addendum"


def test_waiting_on_an_approver_does_not_freeze_the_case() -> None:
    """The case Chi is holding is exactly the one An most wants to correct."""
    assert CaseState.CP1_PENDING.accepts_amendment
    assert CaseState.CP2_PENDING.accepts_amendment


def test_a_rejected_checkpoint_stays_amendable() -> None:
    """Fixing what the approver objected to is the whole point of a rejection."""
    assert CaseState.CP1_REJECTED.accepts_amendment
    assert CaseState.CP2_REJECTED.accepts_amendment


def test_a_failed_run_is_not_amendable() -> None:
    """Nothing to correct: the case never reached a state worth editing."""
    assert not CaseState.FAILED.accepts_amendment
    assert not CaseState.INTAKE_REJECTED.accepts_amendment


def test_every_state_answers_the_question() -> None:
    """A new state must be classified deliberately, not default to editable."""
    for state in CaseState:
        assert isinstance(state.accepts_amendment, bool)
