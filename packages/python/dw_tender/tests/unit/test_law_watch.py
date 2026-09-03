"""What the law watcher tells people, and what it refuses to say.

The sweep exists for a gap nobody watches: a package cites an article, derives
a deadline, and waits. These pin the three judgements it makes in that gap —
when a change is real, when silence is the honest answer, and how often the
same change may be reported.
"""

from __future__ import annotations

import pathlib
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_platform.application.access_context import AccessContext
from dw_tender.adapters.preparation.rules_loader import load_procurement_rules
from dw_tender.application.preparation.law_watch import (
    LawChangeScanner,
    LegalPosition,
    LegalPositionReaderPort,
)
from dw_tender.domain.preparation.entities import (
    ArtifactStatus,
    ArtifactType,
    BusinessDomain,
    CaseState,
    PreparationArtifact,
    PreparationCase,
    ProcurementType,
)
from dw_tender.domain.preparation.notifications import IntakeNotificationType
from dw_tender.domain.value_objects.ids import ArtifactId, PreparationCaseId

pytestmark = pytest.mark.unit


TENANT = uuid.uuid4()
WORKSPACE = uuid.uuid4()
CASE = uuid.uuid4()
ACTOR = uuid.uuid4()
APPROVER = uuid.uuid4()
NOW = datetime(2026, 8, 24, tzinfo=UTC)


class _Clock:
    def now(self) -> datetime:
        return NOW


class _Ids:
    def new_uuid(self) -> uuid.UUID:
        return uuid.uuid4()


# The real pack, not a stub: who is told depends on the versioned approval
# matrix by package value, and a hand-built tier would not exercise that.
RULES = load_procurement_rules(
    pathlib.Path(__file__).resolve().parents[5]
    / "configs"
    / "policies"
    / "dw01"
    / "procurement_rules_v1.yaml"
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


def _case(state: CaseState = CaseState.CP2_PENDING) -> PreparationCase:
    return PreparationCase(
        id=PreparationCaseId(CASE),
        tenant_id=TenantId(TENANT),
        workspace_id=WorkspaceId(WORKSPACE),
        title="Mua 200 màn hình cho team AI FDX",
        description="",
        source_pr_ref="PR-1",
        estimated_value_minor=300_000_000_000,
        currency="VND",
        deadline="90 ngày",
        owner_name="Nguyễn Văn An",
        procurement_type=ProcurementType.GOODS,
        business_domain=BusinessDomain.INFORMATION_TECHNOLOGY,
        created_by=UserId(ACTOR),
        state=state,
    )


def _approach(extracted: dict[str, Any] | None) -> PreparationArtifact:
    return PreparationArtifact(
        id=ArtifactId(uuid.uuid4()),
        tenant_id=TenantId(TENANT),
        workspace_id=WorkspaceId(WORKSPACE),
        case_id=PreparationCaseId(CASE),
        artifact_type=ArtifactType.PROCUREMENT_APPROACH,
        schema_version="1.0",
        artifact_version=1,
        status=ArtifactStatus.DRAFT,
        content={"legal_constraints": {"extracted": extracted, "applied_window_days": 22}},
        created_by=UserId(ACTOR),
    )


@dataclass
class _Artifacts:
    rows: list[PreparationArtifact] = field(default_factory=list)

    async def latest(self, _case_id: Any, kind: ArtifactType) -> PreparationArtifact | None:
        matching = [a for a in self.rows if a.artifact_type is kind]
        return max(matching, key=lambda a: a.artifact_version) if matching else None

    async def add(self, artifact: PreparationArtifact) -> None:
        self.rows.append(artifact)

    async def list_for_case(self, _case_id: Any) -> list[PreparationArtifact]:
        return self.rows


@dataclass
class _Notifications:
    jobs: list[Any] = field(default_factory=list)
    staffed: bool = True

    async def enqueue(self, job: Any) -> None:
        self.jobs.append(job)

    async def find_recipient_for_role(
        self, _role: str, *, exclude: UserId | None = None
    ) -> UserId | None:
        return UserId(APPROVER) if self.staffed else None


@dataclass
class _Cases:
    pending: list[PreparationCase] = field(default_factory=list)

    async def list_pending_law_review(self, limit: int = 20) -> list[PreparationCase]:
        return self.pending[:limit]

    async def get(self, _case_id: Any) -> PreparationCase | None:
        return self.pending[0] if self.pending else None

    async def save(self, case: PreparationCase) -> None:  # pragma: no cover - unused
        raise AssertionError("the watcher must not modify the case")


@dataclass
class _Uow:
    cases: _Cases
    artifacts: _Artifacts
    notifications: _Notifications
    committed: int = 0

    async def commit(self) -> None:
        self.committed += 1


def _factory(uow: _Uow) -> Any:
    @asynccontextmanager
    async def factory(_tenant: TenantId) -> Any:
        yield uow

    return factory


def build(
    *,
    drafted: dict[str, Any] | None,
    current: LegalPosition | None,
    state: CaseState = CaseState.CP2_PENDING,
) -> tuple[LawChangeScanner, _Uow]:
    uow = _Uow(
        cases=_Cases(pending=[_case(state)]),
        artifacts=_Artifacts(rows=[_approach(drafted)]),
        notifications=_Notifications(),
    )

    async def read_current(_case: PreparationCase, _context: AccessContext) -> LegalPosition | None:
        return current

    scanner = LawChangeScanner(
        uow_factory=_factory(uow),
        read_current=cast(LegalPositionReaderPort, read_current),
        rules=RULES,
        clock=_Clock(),
        id_generator=_Ids(),
    )
    return scanner, uow


DRAFTED = {
    "min_bid_preparation_days": 18,
    "article_ref": "Điều 45 khoản 1",
    "source_quote": "…tối thiểu là 18 ngày…",
}


@pytest.mark.asyncio
async def test_a_longer_minimum_reaches_the_person_holding_the_decision() -> None:
    scanner, uow = build(
        drafted=DRAFTED,
        current=LegalPosition(25, "Điều 45 khoản 1", "…tối thiểu là 25 ngày…"),
    )

    report = await scanner.poll_once(_context())

    assert report.changed and "18 → 25 ngày" in report.changed[0]
    job = next(j for j in uow.notifications.jobs)
    assert job.event_type is IntakeNotificationType.LAW_CHANGE_DETECTED
    assert job.recipient_user_id == UserId(APPROVER)
    assert job.payload["before"] == 18
    assert job.payload["after"] == 25


@pytest.mark.asyncio
async def test_the_approval_is_left_standing() -> None:
    """Advice, not an action: a search result must not undo work under way."""
    scanner, uow = build(drafted=DRAFTED, current=LegalPosition(25, "Điều 45 khoản 1", "…25 ngày…"))

    await scanner.poll_once(_context())

    # _Cases.save raises if called; reaching here means the case was untouched.
    assert uow.cases.pending[0].state is CaseState.CP2_PENDING


@pytest.mark.asyncio
async def test_the_same_change_is_reported_once_however_often_the_sweep_runs() -> None:
    """A watcher that repeats itself every six hours gets muted, and then the
    one alert that mattered goes unread with the rest."""
    scanner, uow = build(drafted=DRAFTED, current=LegalPosition(25, "Điều 45 khoản 1", "…25 ngày…"))
    context = _context()

    await scanner.poll_once(context)
    await scanner.poll_once(context)
    await scanner.poll_once(context)

    assert len(uow.notifications.jobs) == 1


@pytest.mark.asyncio
async def test_unchanged_law_says_nothing_but_still_leaves_a_record() -> None:
    """ "We checked and it still holds" is the answer to an auditor's question."""
    scanner, uow = build(drafted=DRAFTED, current=LegalPosition(18, "Điều 45 khoản 1", "…18 ngày…"))

    report = await scanner.poll_once(_context())

    assert report.checked and not report.changed
    assert not uow.notifications.jobs
    reviews = [a for a in uow.artifacts.rows if a.artifact_type is ArtifactType.LAW_REVIEW]
    assert len(reviews) == 1 and reviews[0].content["changed"] is False


@pytest.mark.asyncio
async def test_reworded_but_identical_law_is_not_a_change() -> None:
    """Sources reformat constantly; a diff that fires on wording gets ignored."""
    scanner, uow = build(
        drafted=DRAFTED,
        current=LegalPosition(18, "điều 45 khoản 1  ", "Một cách diễn đạt khác, vẫn 18 ngày."),
    )

    report = await scanner.poll_once(_context())

    assert not report.changed
    assert not uow.notifications.jobs


@pytest.mark.asyncio
async def test_a_failed_lookup_is_not_reported_as_a_change() -> None:
    """Unreachable sources and "the law moved" must never look alike."""
    scanner, uow = build(drafted=DRAFTED, current=None)

    report = await scanner.poll_once(_context())

    assert not report.changed
    assert not uow.notifications.jobs
    assert report.skipped


@pytest.mark.asyncio
async def test_a_case_drafted_without_a_verified_constraint_is_skipped() -> None:
    """No cited position means nothing to compare — the default window applied."""
    scanner, uow = build(drafted=None, current=LegalPosition(25, "Điều 45", "…25 ngày…"))

    report = await scanner.poll_once(_context())

    assert not report.checked and report.skipped
    assert not uow.notifications.jobs


@pytest.mark.asyncio
async def test_an_unstaffed_role_drops_the_alert_rather_than_crashing() -> None:
    scanner, uow = build(drafted=DRAFTED, current=LegalPosition(25, "Điều 45 khoản 1", "…25 ngày…"))
    uow.notifications.staffed = False

    report = await scanner.poll_once(_context())

    assert report.changed
    assert not uow.notifications.jobs
