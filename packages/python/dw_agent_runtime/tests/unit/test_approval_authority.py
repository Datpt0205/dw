"""A checkpoint reserved for one role must refuse every other role.

Routing a card to the right person is a courtesy; refusing the wrong person is
the control. These exercise ``ApproveAndResumeService.decide`` directly so the
guarantee does not depend on which personas happen to be seeded — nothing here
re-implements the rule it is checking.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import pytest

from dw_agent_runtime.approval_flow import ApproveAndResumeService
from dw_kernel.errors import ConflictError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.domain.approval import ApprovalRequest

TENANT = uuid.uuid4()
WORKSPACE = uuid.uuid4()


def _request(required_role: str, requested_by: uuid.UUID) -> ApprovalRequest:
    return ApprovalRequest(
        id=uuid.uuid4(),
        tenant_id=TenantId(TENANT),
        workspace_id=WorkspaceId(WORKSPACE),
        approval_type="preparation.cp2",
        requested_by=UserId(requested_by),
        reason="Duyệt bộ hồ sơ mời thầu chính thức",
        payload={"case_id": str(uuid.uuid4()), "required_role": required_role},
    )


def _context(principal: uuid.UUID, *roles: str) -> AccessContext:
    return AccessContext(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        principal_id=principal,
        roles=frozenset(roles),
        scopes=frozenset({"approvals.decide"}),
        plan_id="pro",
    )


@dataclass
class _Approvals:
    request: ApprovalRequest

    async def get(self, approval_id: uuid.UUID) -> ApprovalRequest:
        return self.request


@dataclass
class _Uow:
    approvals: _Approvals


def _uow_factory(request: ApprovalRequest) -> Any:
    @asynccontextmanager
    async def factory(_context: AccessContext) -> Any:
        yield _Uow(approvals=_Approvals(request))

    return factory


def _service(request: ApprovalRequest) -> ApproveAndResumeService:
    # runner/run_store/clock/id_generator are never reached: both guards refuse
    # before anything is recorded or resumed. Passing None proves that.
    return ApproveAndResumeService(
        uow_factory=_uow_factory(request),
        runner=None,  # type: ignore[arg-type]
        run_store=None,  # type: ignore[arg-type]
        clock=None,  # type: ignore[arg-type]
        id_generator=None,  # type: ignore[arg-type]
    )


async def _decide(request: ApprovalRequest, context: AccessContext) -> ApprovalRequest:
    return await _service(request).decide(
        approval_id=request.id,
        approve=True,
        comment="Đã kiểm tra hồ sơ",
        context=context,
        authorization=ScopeAuthorizationService(),
        channel="zalo",
    )


async def test_specialist_cannot_decide_a_head_only_checkpoint() -> None:
    request = _request("procurement_head", requested_by=uuid.uuid4())
    with pytest.raises(ConflictError, match="reserved for another role"):
        await _decide(request, _context(uuid.uuid4(), "approver"))


async def test_requester_cannot_decide_their_own_checkpoint() -> None:
    person = uuid.uuid4()
    request = _request("procurement_head", requested_by=person)
    with pytest.raises(ConflictError, match="separation of duties"):
        await _decide(request, _context(person, "procurement_head"))


async def test_holding_the_scope_alone_is_not_authority() -> None:
    """The scope opens the endpoint; the stamped role decides who may sign."""
    request = _request("procurement_head", requested_by=uuid.uuid4())
    with pytest.raises(ConflictError, match="reserved for another role"):
        await _decide(request, _context(uuid.uuid4()))
