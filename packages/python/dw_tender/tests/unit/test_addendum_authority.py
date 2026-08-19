"""Only the procuring entity may issue an addendum — enforced, not routed.

An addendum goes to everyone who received the invitation, so the party that
issued the invitation is the party that may change it. The requester proposes;
procurement files.

The chat router already made that split, and the split was correct. What was
missing is that the split was the ONLY thing holding: the handler itself asked
for ``tender.write``, which is what lets a requester open a case in the first
place. Reaching the mutation another way — the decision card's action, the API
— skipped the router and passed.

These call the handler directly, which is where the guarantee has to live.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from dw_kernel.errors import PermissionDeniedError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_tender.application.preparation.handlers import (
    ProposeAddendumCommand,
    ProposePreparationAddendumHandler,
    SubmitAddendumCommand,
    SubmitPreparationAddendumHandler,
)
from dw_tender.domain.preparation.entities import (
    BusinessDomain,
    CaseState,
    PreparationCase,
    ProcurementType,
)
from dw_tender.domain.value_objects.ids import PreparationCaseId

TENANT = uuid.uuid4()
WORKSPACE = uuid.uuid4()
CASE = uuid.uuid4()
REQUESTER = uuid.uuid4()
PROCUREMENT = uuid.uuid4()

# What the requester holds: enough to open a case, and nothing beyond it.
REQUESTER_SCOPES = frozenset({"tender.read", "tender.write"})
PROCUREMENT_SCOPES = REQUESTER_SCOPES | {"approvals.decide"}


class _Clock:
    def now(self) -> datetime:
        return datetime(2026, 8, 19, tzinfo=UTC)


class _Ids:
    def new_uuid(self) -> uuid.UUID:
        return uuid.uuid4()


def _context(principal: uuid.UUID, scopes: frozenset[str]) -> AccessContext:
    return AccessContext(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        principal_id=principal,
        roles=frozenset({"member"}),
        scopes=scopes,
        plan_id="pro",
    )


def _case() -> PreparationCase:
    return PreparationCase(
        id=PreparationCaseId(CASE),
        tenant_id=TenantId(TENANT),
        workspace_id=WorkspaceId(WORKSPACE),
        title="Mua màn hình cho team AI FDX",
        created_by=UserId(REQUESTER),
        estimated_value_minor=300_000_000_000,
        deadline="90 ngày",
        procurement_type=ProcurementType.GOODS,
        business_domain=BusinessDomain.INFORMATION_TECHNOLOGY,
        state=CaseState.PUBLISHED,
    )


@dataclass
class _Cases:
    case: PreparationCase

    async def get(self, _case_id: Any) -> PreparationCase:
        return self.case

    async def save(self, _case: PreparationCase) -> None:
        return None


@dataclass
class _Notifications:
    jobs: list[Any] = field(default_factory=list)

    async def enqueue(self, job: Any) -> None:
        self.jobs.append(job)

    async def find_recipient_for_role(self, _role: str) -> uuid.UUID:
        return PROCUREMENT


@dataclass
class _Documents:
    rows: list[Any] = field(default_factory=list)

    async def add(self, document: Any) -> None:
        self.rows.append(document)


@dataclass
class _Artifacts:
    rows: list[Any] = field(default_factory=list)

    async def latest(self, _case_id: Any, _kind: Any) -> None:
        return None

    async def add(self, artifact: Any) -> None:
        self.rows.append(artifact)


@dataclass
class _Uow:
    cases: _Cases
    notifications: _Notifications
    documents: _Documents
    artifacts: _Artifacts

    async def commit(self) -> None:
        return None


class _Storage:
    async def put_object(self, key: str, _content: bytes, _content_type: str) -> str:
        return key


def _uow_factory(uow: _Uow) -> Any:
    @asynccontextmanager
    async def factory(_tenant: Any) -> Any:
        yield uow

    return factory


def _build() -> tuple[SubmitPreparationAddendumHandler, ProposePreparationAddendumHandler, _Uow]:
    uow = _Uow(_Cases(_case()), _Notifications(), _Documents(), _Artifacts())
    submit = SubmitPreparationAddendumHandler(
        uow_factory=_uow_factory(uow),
        storage=_Storage(),  # type: ignore[arg-type]
        authorization=ScopeAuthorizationService(),
        clock=_Clock(),
        id_generator=_Ids(),
    )
    propose = ProposePreparationAddendumHandler(
        uow_factory=_uow_factory(uow),
        authorization=ScopeAuthorizationService(),
        clock=_Clock(),
        id_generator=_Ids(),
    )
    return submit, propose, uow


def _submit_command() -> SubmitAddendumCommand:
    return SubmitAddendumCommand(
        filename="addendum.md",
        content_type="text/markdown",
        content=b"# Addendum\nGia hia han them 10 ngay.\n",
        change_summary="Gia hạn nộp thầu thêm 10 ngày",
        impact_summary="Hạn nộp lùi 10 ngày",
    )


async def test_the_requester_cannot_file_an_addendum_even_off_the_router() -> None:
    """tender.write opens a case; it must not also issue an addendum."""
    submit, _, uow = _build()
    with pytest.raises(PermissionDeniedError):
        await submit.handle(CASE, _submit_command(), _context(REQUESTER, REQUESTER_SCOPES))
    assert uow.documents.rows == [], "nothing was written before the refusal"


async def test_procurement_can_file_one() -> None:
    submit, _, uow = _build()
    await submit.handle(CASE, _submit_command(), _context(PROCUREMENT, PROCUREMENT_SCOPES))
    assert uow.documents.rows, "the addendum document was stored"


async def test_the_requester_can_still_propose() -> None:
    """Refusing to file must not refuse to ask — that is the whole flow."""
    _, propose, uow = _build()
    await propose.handle(
        CASE,
        ProposeAddendumCommand(
            change_summary="Gia hạn nộp thầu thêm 10 ngày",
            impact_summary="Hạn nộp lùi 10 ngày",
            proposer_name="Nguyễn Văn An",
        ),
        _context(REQUESTER, REQUESTER_SCOPES),
    )
    assert uow.notifications.jobs, "the proposal reached procurement"
    assert uow.notifications.jobs[0].recipient_user_id == PROCUREMENT
