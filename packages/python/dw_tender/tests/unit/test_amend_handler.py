"""Does the amendment actually land — on the case, and on the paperwork?

The boundary tests say which states may be amended. These say what happens
when one is: the figure on the case really moves, a supplier list that lives on
an artifact really gets a new version, the card an approver is holding is
withdrawn, and a change that changes nothing is refused rather than reported.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from dw_kernel.errors import ConflictError, DomainError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.domain.approval import ApprovalRequest, ApprovalStatus
from dw_tender.application.preparation.amend import (
    AmendCaseCommand,
    AmendPreparationCaseHandler,
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
from dw_tender.domain.value_objects.ids import ArtifactId, PreparationCaseId

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
WORKSPACE = uuid.uuid4()
CASE = uuid.uuid4()
ACTOR = uuid.uuid4()
NOW = datetime(2026, 8, 18, tzinfo=UTC)


class _Clock:
    def now(self) -> datetime:
        return NOW


class _Ids:
    def new_uuid(self) -> uuid.UUID:
        return uuid.uuid4()


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


def _suppliers(names: list[str]) -> PreparationArtifact:
    return PreparationArtifact(
        id=ArtifactId(uuid.uuid4()),
        tenant_id=TenantId(TENANT),
        workspace_id=WorkspaceId(WORKSPACE),
        case_id=PreparationCaseId(CASE),
        artifact_type=ArtifactType.SUPPLIER_INPUT,
        schema_version="1.0",
        artifact_version=1,
        status=ArtifactStatus.DRAFT,
        content={"source": "manual_entry", "suppliers": [{"name": n} for n in names]},
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

    async def enqueue(self, job: Any) -> None:
        self.jobs.append(job)


@dataclass
class _Cases:
    """Enforces the real repository's optimistic lock.

    SQL updates ``where version = case.version - 1``, so exactly one increment
    may happen between load and save. A fake that ignores that let an amendment
    bump twice and pass every unit test, then fail on a live case.
    """

    case: PreparationCase | None
    saved: list[PreparationCase] = field(default_factory=list)
    loaded_version: int = 0

    async def get(self, _case_id: Any) -> PreparationCase | None:
        if self.case is not None:
            self.loaded_version = self.case.version
        return self.case

    async def save(self, case: PreparationCase) -> None:
        if case.version != self.loaded_version + 1:
            raise ConflictError(
                "preparation case was modified concurrently",
                details={"loaded": self.loaded_version, "saving": case.version},
            )
        self.loaded_version = case.version
        self.saved.append(case)


@dataclass
class _Uow:
    cases: _Cases
    artifacts: _Artifacts
    notifications: _Notifications
    committed: int = 0

    async def commit(self) -> None:
        self.committed += 1


@dataclass
class _Approvals:
    pending: list[ApprovalRequest] = field(default_factory=list)
    saved: list[ApprovalRequest] = field(default_factory=list)

    async def list_pending(self, limit: int = 50) -> list[ApprovalRequest]:
        return self.pending

    async def save(self, request: ApprovalRequest) -> None:
        self.saved.append(request)


@dataclass
class _PlatformUow:
    approvals: _Approvals

    async def commit(self) -> None:
        return None


@dataclass
class _Runner:
    calls: list[tuple[uuid.UUID, str]] = field(default_factory=list)

    async def handle(self, case_id: uuid.UUID, _context: Any, *, channel: str = "web") -> uuid.UUID:
        self.calls.append((case_id, channel))
        return uuid.uuid4()


def _cp2_card() -> ApprovalRequest:
    from dw_kernel.ids import TenantId as TId
    from dw_kernel.ids import WorkspaceId as WId

    return ApprovalRequest(
        id=uuid.uuid4(),
        tenant_id=TId(TENANT),
        workspace_id=WId(WORKSPACE),
        approval_type="preparation.cp2",
        requested_by=UserId(uuid.uuid4()),
        reason="Duyệt bộ hồ sơ mời thầu chính thức",
        payload={"case_id": str(CASE), "checkpoint": "CP2"},
    )


def _build(
    case: PreparationCase,
    artifacts: list[PreparationArtifact] | None = None,
    pending: list[ApprovalRequest] | None = None,
    runner: _Runner | None = None,
) -> tuple[AmendPreparationCaseHandler, _Uow, _Approvals, _Runner]:
    uow = _Uow(
        cases=_Cases(case),
        artifacts=_Artifacts(list(artifacts or [])),
        notifications=_Notifications(),
    )
    approvals = _Approvals(pending=list(pending or []))
    run = runner or _Runner()

    @asynccontextmanager
    async def prep_factory(_tenant: Any) -> Any:
        yield uow

    @asynccontextmanager
    async def platform_factory(_ctx: Any) -> Any:
        yield _PlatformUow(approvals)

    handler = AmendPreparationCaseHandler(
        uow_factory=prep_factory,  # type: ignore[arg-type]
        platform_uow_factory=platform_factory,  # type: ignore[arg-type]
        authorization=ScopeAuthorizationService(),
        clock=_Clock(),
        id_generator=_Ids(),
        run_case=run,  # type: ignore[arg-type]
    )
    return handler, uow, approvals, run


# ------------------------------------------------- the figure really moves --
async def test_the_budget_on_the_case_actually_changes() -> None:
    case = _case()
    handler, uow, _, _ = _build(case)
    result = await handler.handle(
        CASE, AmendCaseCommand(estimated_value_minor=250_000_000_000), _context()
    )
    assert case.estimated_value_minor == 250_000_000_000
    assert uow.cases.saved, "the case was persisted"
    assert any("giá trị gói" in c for c in result.changes)


async def test_the_supplier_list_gets_a_new_artifact_version() -> None:
    """Suppliers live on an artifact — reporting the change is not making it."""
    case = _case()
    handler, uow, _, _ = _build(case, artifacts=[_suppliers(["Thiết bị Việt", "Minh Long"])])
    result = await handler.handle(
        CASE,
        AmendCaseCommand(supplier_names=("Thiết bị Việt", "Minh Long", "Sao Mai")),
        _context(),
    )
    versions = [a for a in uow.artifacts.rows if a.artifact_type is ArtifactType.SUPPLIER_INPUT]
    assert len(versions) == 2, "a new version, not an edit in place"
    latest = max(versions, key=lambda a: a.artifact_version)
    stored = latest.content["suppliers"]
    assert isinstance(stored, list)
    assert [s["name"] for s in stored] == [
        "Thiết bị Việt",
        "Minh Long",
        "Sao Mai",
    ]
    assert any("Sao Mai" in c for c in result.changes)


async def test_an_unchanged_supplier_list_is_not_reported_as_a_change() -> None:
    case = _case()
    handler, _, _, _ = _build(case, artifacts=[_suppliers(["Thiết bị Việt"])])
    with pytest.raises(DomainError):
        await handler.handle(CASE, AmendCaseCommand(supplier_names=("Thiết bị Việt",)), _context())


async def test_saying_the_same_number_again_changes_nothing() -> None:
    handler, _, _, _ = _build(_case())
    with pytest.raises(DomainError):
        await handler.handle(
            CASE, AmendCaseCommand(estimated_value_minor=300_000_000_000), _context()
        )


# ------------------------------------------- the approver is not left stale --
async def test_a_pending_checkpoint_is_withdrawn_and_the_owner_told() -> None:
    card = _cp2_card()
    case = _case()
    handler, uow, approvals, _ = _build(case, pending=[card])
    result = await handler.handle(
        CASE, AmendCaseCommand(estimated_value_minor=250_000_000_000), _context()
    )
    assert card.status is ApprovalStatus.CANCELLED
    assert approvals.saved == [card]
    assert result.withdrew_checkpoint == "CP2"
    assert uow.notifications.jobs, "somebody has to be told the ground moved"
    assert "thu hồi" in uow.notifications.jobs[0].payload["heading"]


async def test_a_checkpoint_for_another_case_is_left_alone() -> None:
    other = _cp2_card()
    other.payload["case_id"] = str(uuid.uuid4())
    handler, _, approvals, _ = _build(_case(), pending=[other])
    result = await handler.handle(CASE, AmendCaseCommand(deadline="120 ngày"), _context())
    assert other.status is ApprovalStatus.PENDING
    assert approvals.saved == []
    assert result.withdrew_checkpoint == ""


async def test_a_card_without_a_checkpoint_label_is_named_from_its_type() -> None:
    """Cards carry "preparation.cp2"; the person waiting knows it as CP2."""
    card = _cp2_card()
    card.payload.pop("checkpoint")
    handler, _, _, _ = _build(_case(), pending=[card])
    result = await handler.handle(CASE, AmendCaseCommand(deadline="120 ngày"), _context())
    assert result.withdrew_checkpoint == "CP2"


async def test_the_gates_are_re_evaluated_against_the_new_numbers() -> None:
    handler, _, _, runner = _build(_case())
    result = await handler.handle(
        CASE, AmendCaseCommand(estimated_value_minor=250_000_000_000), _context()
    )
    assert runner.calls == [(CASE, "amend")]
    assert result.rerun_id is not None


async def test_changing_several_things_at_once_still_saves_cleanly() -> None:
    """Budget, deadline and suppliers in one message — one save, one version."""
    case = _case()
    before_version = case.version
    handler, uow, _, _ = _build(case, artifacts=[_suppliers(["Thiết bị Việt"])])
    result = await handler.handle(
        CASE,
        AmendCaseCommand(
            estimated_value_minor=250_000_000_000,
            deadline="120 ngày",
            supplier_names=("Thiết bị Việt", "Sao Mai"),
        ),
        _context(),
    )
    assert len(result.changes) == 3
    assert case.version == before_version + 1
    assert len(uow.cases.saved) == 1


async def test_the_case_is_left_in_a_state_the_re_run_will_accept() -> None:
    """The bug this pins: withdraw the card, then fail to restart — stranded."""
    case = _case(CaseState.CP2_PENDING)
    handler, _, _, _ = _build(case)
    await handler.handle(CASE, AmendCaseCommand(deadline="120 ngày"), _context())
    assert case.state is CaseState.INTAKE_READY
    case.start_run(uuid.uuid4())  # the very call that used to raise


# ----------------------------------------------------- and it knows to stop --
async def test_an_official_package_is_refused_with_a_reason() -> None:
    handler, _, _, runner = _build(_case(CaseState.PUBLISHED))
    with pytest.raises(ConflictError, match="addendum"):
        await handler.handle(
            CASE, AmendCaseCommand(estimated_value_minor=250_000_000_000), _context()
        )
    assert runner.calls == [], "nothing re-ran"


async def test_writing_requires_the_write_scope() -> None:
    from dw_kernel.errors import PermissionDeniedError

    handler, _, _, _ = _build(_case())
    reader = _context().model_copy(update={"scopes": frozenset({"tender.read"})})
    with pytest.raises(PermissionDeniedError):
        await handler.handle(CASE, AmendCaseCommand(deadline="120 ngày"), reader)
