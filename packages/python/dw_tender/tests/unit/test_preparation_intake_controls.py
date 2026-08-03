"""DW01 upload-only intake and clarification state controls."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_tender.domain.exceptions import TenderDomainError
from dw_tender.domain.preparation.entities import CaseState, PreparationCase
from dw_tender.domain.value_objects.ids import PreparationCaseId


def _case() -> PreparationCase:
    return PreparationCase(
        id=PreparationCaseId(uuid.uuid4()),
        tenant_id=TenantId(uuid.uuid4()),
        workspace_id=WorkspaceId(uuid.uuid4()),
        title="Mua laptop",
        created_by=UserId(uuid.uuid4()),
    )


@pytest.mark.unit
def test_creator_cannot_verify_their_own_uploaded_intake() -> None:
    case = _case()
    with pytest.raises(TenderDomainError, match="cannot verify"):
        case.verify_intake(case.created_by, datetime.now(tz=UTC))
    assert case.state is CaseState.DRAFT


@pytest.mark.unit
def test_distinct_approver_can_reject_intake_but_creator_cannot() -> None:
    case = _case()
    with pytest.raises(TenderDomainError, match="cannot reject"):
        case.reject_intake(case.created_by)
    case.reject_intake(UserId(uuid.uuid4()))
    assert case.state is CaseState.INTAKE_REJECTED
    with pytest.raises(TenderDomainError, match="only a draft"):
        case.reject_intake(UserId(uuid.uuid4()))


@pytest.mark.unit
def test_distinct_controller_verifies_intake_before_run() -> None:
    case = _case()
    controller = UserId(uuid.uuid4())
    case.verify_intake(controller, datetime.now(tz=UTC))
    run_id = uuid.uuid4()
    case.start_run(run_id)
    assert case.intake_verified_by == controller
    assert case.state is CaseState.ANALYZING
    assert case.last_run_id == run_id


@pytest.mark.unit
def test_draft_cannot_run_and_clarification_can_reopen() -> None:
    case = _case()
    with pytest.raises(TenderDomainError, match="cannot run"):
        case.start_run(uuid.uuid4())

    case.verify_intake(UserId(uuid.uuid4()), datetime.now(tz=UTC))
    case.advance(CaseState.WAITING_CLARIFICATION, "clarification")
    case.reopen_after_clarification()
    assert case.state is CaseState.INTAKE_READY


@pytest.mark.unit
def test_post_cp2_upload_only_state_machine_requires_order() -> None:
    case = _case()
    with pytest.raises(TenderDomainError, match="official package"):
        case.record_publication()

    case.advance(CaseState.PACKAGE_OFFICIAL, "official")
    case.record_publication()
    case.record_submission()
    case.record_submission()
    case.complete_cp4_handoff()
    assert case.state is CaseState.COMPLETED
    assert case.current_step == "completed"
