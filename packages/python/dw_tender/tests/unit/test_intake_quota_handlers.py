"""Submitting a justification, and getting it in front of somebody.

The record is only half of it. A justification nobody is told about is a form
sitting in a table, and the person who wrote it waits without knowing what for.

Two refusals matter as much as the write: too short, and not actually blocked.
The second stops the mechanism being used as a general-purpose note — a record
claiming somebody was over quota when they were not would read as evidence
later.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from dw_kernel.errors import DomainError
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_tender.application.preparation.intake_quota import IntakeQuotaRules
from dw_tender.application.preparation.intake_quota_guard import IntakeQuotaGuard
from dw_tender.application.preparation.intake_quota_handlers import (
    SubmitQuotaJustificationCommand,
    SubmitQuotaJustificationHandler,
)
from dw_tender.application.preparation.ports import OpenedCaseRow
from dw_tender.domain.preparation.entities import CaseState
from dw_tender.domain.preparation.notifications import IntakeNotificationType
from dw_tender.domain.preparation.rework import ExplanationKind

TENANT = uuid.uuid4()
WORKSPACE = uuid.uuid4()
ACTOR = uuid.uuid4()
APPROVER = uuid.uuid4()
NOW = datetime(2026, 9, 20, 3, 0, tzinfo=UTC)

REASON = (
    "Đợt này là thiết bị cho nhóm kiểm thử mới thành lập theo QĐ 145, không gộp được "
    "với hai đợt trước vì khác nguồn ngân sách."
)


class _Clock:
    def now(self) -> datetime:
        return NOW


class _Ids:
    def new_uuid(self) -> uuid.UUID:
        return uuid.uuid4()


def _rules(threshold: int = 2) -> IntakeQuotaRules:
    return IntakeQuotaRules(
        policy_version="1.0.0",
        source="Quy chế §4.2",
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


def _row(day: int) -> OpenedCaseRow:
    return OpenedCaseRow(
        case_id=uuid.uuid4(), opened_at=datetime(2026, 9, day, tzinfo=UTC), state=CaseState.DRAFT
    )


@dataclass
class _Cases:
    rows: list[OpenedCaseRow]

    async def list_opened_by(self, _creator: Any, *, since: datetime) -> list[OpenedCaseRow]:
        return [r for r in self.rows if r.opened_at >= since]


@dataclass
class _Explanations:
    added: list[Any] = field(default_factory=list)

    async def add(self, record: Any) -> None:
        self.added.append(record)

    async def has_approved_since(self, _c: Any, *, since: datetime, kind: str = "rework") -> bool:
        return False


@dataclass
class _Notifications:
    recipient: uuid.UUID | None
    jobs: list[Any] = field(default_factory=list)
    excluded: Any = None

    async def find_recipient_for_role(self, role: str, *, exclude: Any = None) -> Any:
        self.excluded = exclude
        self.role_asked = role
        return self.recipient

    async def enqueue(self, job: Any) -> None:
        self.jobs.append(job)


@dataclass
class _Uow:
    cases: _Cases
    explanations: _Explanations
    notifications: _Notifications
    committed: int = 0

    async def commit(self) -> None:
        self.committed += 1


def _build(
    rows: list[OpenedCaseRow], *, recipient: uuid.UUID | None = APPROVER, threshold: int = 2
) -> tuple[SubmitQuotaJustificationHandler, _Uow]:
    uow = _Uow(_Cases(rows), _Explanations(), _Notifications(recipient))

    @asynccontextmanager
    async def factory(_tenant: Any) -> Any:
        yield uow

    guard = IntakeQuotaGuard(
        uow_factory=factory,  # type: ignore[arg-type]
        rules=_rules(threshold),
        clock=_Clock(),
    )
    handler = SubmitQuotaJustificationHandler(
        uow_factory=factory,  # type: ignore[arg-type]
        authorization=ScopeAuthorizationService(),
        guard=guard,
        clock=_Clock(),
        id_generator=_Ids(),
    )
    return handler, uow


OVER = [_row(3), _row(11)]


# ------------------------------------------------------------- it is stored --
async def test_the_justification_is_stored_under_its_own_kind() -> None:
    handler, uow = _build(OVER)
    await handler.handle(SubmitQuotaJustificationCommand(reason_text=REASON), _context())
    [record] = uow.explanations.added
    assert record.kind is ExplanationKind.INTAKE_QUOTA
    assert record.context_text == REASON
    assert record.case_id is None, "there is no case — that is what was refused"


async def test_what_the_count_was_is_stamped_not_recomputed_later() -> None:
    handler, uow = _build(OVER)
    await handler.handle(SubmitQuotaJustificationCommand(reason_text=REASON), _context())
    [record] = uow.explanations.added
    assert record.block_count == 2
    assert record.policy_version == "1.0.0"


# ------------------------------------------------- somebody is actually told --
async def test_the_card_goes_to_the_approving_role_and_not_to_the_author() -> None:
    handler, uow = _build(OVER)
    await handler.handle(SubmitQuotaJustificationCommand(reason_text=REASON), _context())
    [job] = uow.notifications.jobs
    assert job.recipient_user_id == APPROVER
    assert uow.notifications.role_asked == "procurement_head"
    assert uow.notifications.excluded.value == ACTOR, "nobody approves their own"


async def test_the_card_carries_the_count_and_the_reason() -> None:
    handler, uow = _build(OVER)
    await handler.handle(SubmitQuotaJustificationCommand(reason_text=REASON), _context())
    [job] = uow.notifications.jobs
    assert job.event_type is IntakeNotificationType.QUOTA_JUSTIFICATION_SUBMITTED
    body = " ".join(job.payload["lines"])
    assert "2/2" in body
    assert "QĐ 145" in body


async def test_the_card_rides_on_a_real_case_of_theirs() -> None:
    """The pipeline requires one, and the approver gets somewhere to land."""
    handler, uow = _build(OVER)
    await handler.handle(SubmitQuotaJustificationCommand(reason_text=REASON), _context())
    [job] = uow.notifications.jobs
    assert job.case_id.value in {row.case_id for row in OVER}


async def test_no_approver_configured_still_records_the_justification() -> None:
    handler, uow = _build(OVER, recipient=None)
    await handler.handle(SubmitQuotaJustificationCommand(reason_text=REASON), _context())
    assert uow.explanations.added, "the writing must not depend on the telling"
    assert uow.notifications.jobs == []


# ----------------------------------------------------------- what it refuses --
async def test_too_short_is_refused_before_anything_is_written() -> None:
    handler, uow = _build(OVER)
    with pytest.raises(DomainError, match="quá ngắn"):
        await handler.handle(SubmitQuotaJustificationCommand(reason_text="bận"), _context())
    assert uow.explanations.added == []
    assert uow.notifications.jobs == []


async def test_somebody_not_over_quota_cannot_file_one() -> None:
    """Otherwise the table fills with records asserting a block that never was."""
    handler, uow = _build([_row(3)])
    with pytest.raises(DomainError, match="chưa chạm ngưỡng"):
        await handler.handle(SubmitQuotaJustificationCommand(reason_text=REASON), _context())
    assert uow.explanations.added == []


async def test_writing_requires_the_write_scope() -> None:
    from dw_kernel.errors import PermissionDeniedError

    handler, _ = _build(OVER)
    reader = _context().model_copy(update={"scopes": frozenset({"tender.read"})})
    with pytest.raises(PermissionDeniedError):
        await handler.handle(SubmitQuotaJustificationCommand(reason_text=REASON), reader)
