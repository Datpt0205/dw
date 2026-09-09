"""The gate, and its safety catch.

The asymmetry that shapes this: letting one extra request through costs a late
justification; refusing somebody wrongly costs their afternoon and their
willingness to use the system honestly next time. So every failure path here
has to end in "nobody is blocked".

The other guarantee is that a block is lifted by a person and not by the
calendar — and that the person who lifted it was answering the right question.
An approved rework explanation must not clear a quota block.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from dw_kernel.errors import ConflictError
from dw_platform.application.access_context import AccessContext
from dw_tender.application.preparation.intake_quota import IntakeQuotaRules
from dw_tender.application.preparation.intake_quota_guard import IntakeQuotaGuard
from dw_tender.application.preparation.ports import OpenedCaseRow
from dw_tender.domain.preparation.entities import CaseState

TENANT = uuid.uuid4()
WORKSPACE = uuid.uuid4()
ACTOR = uuid.uuid4()
NOW = datetime(2026, 9, 20, 3, 0, tzinfo=UTC)


class _Clock:
    def now(self) -> datetime:
        return NOW


def _rules(threshold: int = 2) -> IntakeQuotaRules:
    return IntakeQuotaRules(
        policy_version="1.0.0",
        source="Quy chế mua sắm §4.2",
        enabled_from=None,
        timezone="Asia/Ho_Chi_Minh",
        threshold=threshold,
        burst_window_days=7,
        burst_threshold=0,
        count_closed_unsuccessful=False,
        explanation_min_chars=80,
        approver_role="procurement_head",
        escalate_after_hours=48,
        guidance="Gộp lại thành một yêu cầu sẽ nhanh hơn.",
    )


def _context() -> AccessContext:
    return AccessContext(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        principal_id=ACTOR,
        roles=frozenset({"member"}),
        scopes=frozenset({"tender.write"}),
        plan_id="pro",
    )


def _row(day: int, state: CaseState = CaseState.DRAFT) -> OpenedCaseRow:
    return OpenedCaseRow(
        case_id=uuid.uuid4(),
        opened_at=datetime(2026, 9, day, tzinfo=UTC),
        state=state,
    )


@dataclass
class _Cases:
    rows: list[OpenedCaseRow] = field(default_factory=list)
    explode: bool = False

    async def list_opened_by(self, _creator: Any, *, since: datetime) -> list[OpenedCaseRow]:
        if self.explode:
            raise RuntimeError("database is down")
        return [row for row in self.rows if row.opened_at >= since]


@dataclass
class _Explanations:
    approved_kinds: set[str] = field(default_factory=set)

    async def has_approved_since(
        self, _creator: Any, *, since: datetime, kind: str = "rework"
    ) -> bool:
        return kind in self.approved_kinds


@dataclass
class _Uow:
    cases: _Cases
    explanations: _Explanations


def _guard(
    rows: list[OpenedCaseRow],
    *,
    approved_kinds: set[str] | None = None,
    explode: bool = False,
    threshold: int = 2,
) -> IntakeQuotaGuard:
    uow = _Uow(_Cases(rows, explode=explode), _Explanations(approved_kinds or set()))

    @asynccontextmanager
    async def factory(_tenant: Any) -> Any:
        yield uow

    return IntakeQuotaGuard(
        uow_factory=factory,  # type: ignore[arg-type]
        rules=_rules(threshold),
        clock=_Clock(),
    )


# ----------------------------------------------------------- the happy path --
async def test_under_the_quota_the_gate_lets_you_through() -> None:
    await _guard([_row(3)]).require_not_blocked(_context())


async def test_at_the_quota_the_gate_refuses_with_a_way_out() -> None:
    with pytest.raises(ConflictError) as caught:
        await _guard([_row(3), _row(11)]).require_not_blocked(_context())
    assert caught.value.details["reason"] == "intake_quota_explanation_required"
    assert caught.value.details["used"] == 2
    assert "giải trình" in str(caught.value)


async def test_a_rejected_case_frees_its_slot() -> None:
    rows = [_row(3), _row(11, CaseState.INTAKE_REJECTED)]
    await _guard(rows).require_not_blocked(_context())


# ------------------------------------------------------ lifted by a person --
async def test_an_approved_quota_explanation_lifts_the_block() -> None:
    guard = _guard([_row(3), _row(11)], approved_kinds={"intake_quota"})
    await guard.require_not_blocked(_context())


async def test_an_approved_rework_explanation_does_not_lift_a_quota_block() -> None:
    """Different question, different answer — the kinds must not clear each other."""
    guard = _guard([_row(3), _row(11)], approved_kinds={"rework"})
    with pytest.raises(ConflictError):
        await guard.require_not_blocked(_context())


# ------------------------------------------------------------- fails open --
async def test_a_broken_database_blocks_nobody() -> None:
    guard = _guard([_row(3), _row(11)], explode=True)
    await guard.require_not_blocked(_context())
    assert not (await guard.assess(_context())).available, "and says it could not tell"


async def test_a_disabled_rule_pack_blocks_nobody() -> None:
    guard = _guard([_row(d) for d in range(1, 12)], threshold=0)
    await guard.require_not_blocked(_context())
