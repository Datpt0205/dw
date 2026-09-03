"""What the readiness sweep must never get wrong.

The dangerous failure is not a missed risk — it is a confident "ready" over a
package that moved after its approval, or over a case that has barely started.
Both are pinned here, along with the shape of the score.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_tender.adapters.preparation.rules_loader import load_procurement_rules
from dw_tender.application.preparation.readiness import AssessTenderReadinessHandler
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
RULES = load_procurement_rules(
    Path(__file__).resolve().parents[5]
    / "configs"
    / "policies"
    / "dw01"
    / "procurement_rules_v1.yaml"
)

# 12 tỷ → open tender, minimum 3 suppliers under the rule pack.
VALUE = 12_000_000_000


def _context() -> AccessContext:
    return AccessContext(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        principal_id=ACTOR,
        roles=frozenset({"member"}),
        scopes=frozenset({"tender.read"}),
        plan_id="pro",
    )


def _case() -> PreparationCase:
    return PreparationCase(
        id=PreparationCaseId(CASE),
        tenant_id=TenantId(TENANT),
        workspace_id=WorkspaceId(WORKSPACE),
        title="Mua 200 màn hình cho team AI FDX",
        description="",
        source_pr_ref="PR-1",
        estimated_value_minor=VALUE,
        currency="VND",
        deadline="90 ngày",
        owner_name="Nguyễn Văn An",
        procurement_type=ProcurementType.GOODS,
        business_domain=BusinessDomain.INFORMATION_TECHNOLOGY,
        created_by=UserId(ACTOR),
        state=CaseState.PACKAGE_OFFICIAL,
    )


def _artifact(kind: ArtifactType, version: int, content: dict[str, Any]) -> PreparationArtifact:
    return PreparationArtifact(
        id=ArtifactId(uuid.uuid4()),
        tenant_id=TenantId(TENANT),
        workspace_id=WorkspaceId(WORKSPACE),
        case_id=PreparationCaseId(CASE),
        artifact_type=kind,
        schema_version="1.0",
        artifact_version=version,
        status=ArtifactStatus.DRAFT,
        content=content,
        created_by=UserId(ACTOR),
    )


def _package(version: int = 1) -> PreparationArtifact:
    return _artifact(ArtifactType.SOLICITATION_PACKAGE, version, {"sections": []})


def _criteria(total: int = 100) -> PreparationArtifact:
    return _artifact(
        ArtifactType.EVALUATION_CRITERIA,
        1,
        {"weighted": [{"code": "W1", "text": "Kỹ thuật", "weight": total}]},
    )


def _shortlist(count: int = 3) -> PreparationArtifact:
    return _artifact(
        ArtifactType.SUPPLIER_SHORTLIST,
        1,
        {"shortlist": [{"name": f"NCC {i}"} for i in range(count)]},
    )


def _manifest(versions: dict[ArtifactType, int]) -> PreparationArtifact:
    return _artifact(
        ArtifactType.OFFICIAL_PACKAGE_MANIFEST,
        1,
        {"artifacts": [{"type": k.value, "version": v} for k, v in versions.items()]},
    )


@dataclass
class _Artifacts:
    rows: list[PreparationArtifact]

    async def list_for_case(self, _case_id: Any) -> list[PreparationArtifact]:
        return self.rows


@dataclass
class _Cases:
    case: PreparationCase | None

    async def get(self, _case_id: Any) -> PreparationCase | None:
        return self.case


@dataclass
class _Uow:
    cases: _Cases
    artifacts: _Artifacts


@dataclass
class _Gateway:
    """Stands in for the model. ``boom`` makes the second opinion fail."""

    findings: list[Any] = field(default_factory=list)
    boom: bool = False
    calls: int = 0

    async def generate_structured(self, _request: Any, schema: Any, **_kw: Any) -> Any:
        self.calls += 1
        if self.boom:
            raise RuntimeError("gateway down")
        return schema.model_validate({"findings": self.findings})


def _handler(rows: list[PreparationArtifact], gateway: Any = None) -> AssessTenderReadinessHandler:
    @asynccontextmanager
    async def factory(_tenant: Any) -> Any:
        yield _Uow(cases=_Cases(_case()), artifacts=_Artifacts(rows))

    return AssessTenderReadinessHandler(
        uow_factory=factory,  # type: ignore[arg-type]
        authorization=ScopeAuthorizationService(),
        rules=RULES,
        id_generator=type("G", (), {"new_uuid": staticmethod(uuid.uuid4)})(),
        gateway=gateway,
    )


async def _assess(rows: list[PreparationArtifact], gateway: Any = None) -> Any:
    return await _handler(rows, gateway).handle(CASE, _context())


def _codes(report: Any) -> set[str]:
    return {f.code for f in report.findings}


async def test_a_package_that_moved_after_sealing_is_a_blocker() -> None:
    """The version-mismatch case: sealed v1, an addendum produced v2."""
    report = await _assess(
        [
            _package(version=2),
            _criteria(),
            _shortlist(),
            _manifest({ArtifactType.SOLICITATION_PACKAGE: 1}),
        ]
    )
    assert not report.ready
    assert "package_drift" in _codes(report)
    assert "v1" in report.of("blocker")[0].detail and "v2" in report.of("blocker")[0].detail


async def test_no_drift_when_the_sealed_version_is_still_current() -> None:
    report = await _assess(
        [
            _package(version=3),
            _criteria(),
            _shortlist(),
            _manifest({ArtifactType.SOLICITATION_PACKAGE: 3}),
        ]
    )
    assert report.ready
    assert report.score == 100


async def test_an_empty_case_is_not_ready() -> None:
    """Silence from every check must not read as a clean bill of health."""
    report = await _assess([])
    assert not report.ready
    assert _codes(report) == {"no_package"}


async def test_weights_that_do_not_total_one_hundred_block() -> None:
    report = await _assess([_package(), _criteria(total=90), _shortlist()])
    assert not report.ready
    assert "criteria_weight" in _codes(report)


async def test_too_few_suppliers_blocks_at_this_package_value() -> None:
    report = await _assess([_package(), _criteria(), _shortlist(count=2)])
    assert not report.ready
    finding = next(f for f in report.findings if f.code == "supplier_shortfall")
    assert "2/3" in finding.title


async def test_an_unanswered_blocking_clarification_blocks() -> None:
    rows = [
        _package(),
        _criteria(),
        _shortlist(),
        _artifact(
            ArtifactType.CLARIFICATION_LIST,
            1,
            {"items": [{"id": "c1", "question": "Bảo hành mấy tháng?", "blocking": True}]},
        ),
    ]
    report = await _assess(rows)
    assert "open_clarification" in _codes(report)


async def test_answering_it_clears_the_block() -> None:
    rows = [
        _package(),
        _criteria(),
        _shortlist(),
        _artifact(
            ArtifactType.CLARIFICATION_LIST,
            1,
            {"items": [{"id": "c1", "question": "Bảo hành mấy tháng?", "blocking": True}]},
        ),
        _artifact(
            ArtifactType.CLARIFICATION_RESPONSE,
            1,
            {"answers": [{"clarification_id": "c1", "answer": "36 tháng"}]},
        ),
    ]
    report = await _assess(rows)
    assert report.ready
    assert "open_clarification" not in _codes(report)


async def test_a_non_blocking_clarification_does_not_block() -> None:
    rows = [
        _package(),
        _criteria(),
        _shortlist(),
        _artifact(
            ArtifactType.CLARIFICATION_LIST,
            1,
            {"items": [{"id": "c1", "question": "Màu vỏ?", "blocking": False}]},
        ),
    ]
    assert (await _assess(rows)).ready


async def test_the_red_team_can_only_add_advice_never_a_block() -> None:
    gateway = _Gateway(
        findings=[
            {"severity": "risk", "title": "Cấu hình cổng quá cụ thể", "detail": "…"},
            {"severity": "warning", "title": "Chưa nói VAT", "detail": "…"},
        ]
    )
    report = await _assess([_package(), _criteria(), _shortlist()], gateway)
    assert report.ready, "advisory findings must not flip the verdict"
    assert report.score == 100 - 10 - 4
    assert {f.severity for f in report.findings} == {"risk", "warning"}


async def test_a_failed_second_opinion_is_reported_not_swallowed() -> None:
    report = await _assess([_package(), _criteria(), _shortlist()], _Gateway(boom=True))
    assert "redteam_unavailable" in _codes(report)
    assert report.ready, "the deterministic checks still passed"


async def test_without_a_gateway_the_deterministic_verdict_still_stands() -> None:
    report = await _assess([_package(), _criteria(total=80), _shortlist()], gateway=None)
    assert not report.ready
    assert _codes(report) == {"criteria_weight"}


async def test_findings_price_the_score_additively() -> None:
    """3 blockers + 1 warning = 75 + 4 off a clean 100."""
    report = await _assess([_criteria(total=1), _shortlist(count=0)], _Gateway(boom=True))
    assert len(report.of("blocker")) == 3
    assert report.score == 100 - 75 - 4


async def test_the_score_floors_at_zero() -> None:
    """Four blockers already price at 100; a negative score reads as a bug."""
    rows = [
        _criteria(total=1),
        _shortlist(count=0),
        _artifact(
            ArtifactType.CLARIFICATION_LIST,
            1,
            {"items": [{"id": "c1", "question": "?", "blocking": True}]},
        ),
    ]
    report = await _assess(rows, _Gateway(boom=True))
    assert len(report.of("blocker")) == 4
    assert report.score == 0
    assert not report.ready


async def test_a_missing_case_is_not_silently_ready() -> None:
    @asynccontextmanager
    async def factory(_tenant: Any) -> Any:
        yield _Uow(cases=_Cases(None), artifacts=_Artifacts([]))

    handler = AssessTenderReadinessHandler(
        uow_factory=factory,  # type: ignore[arg-type]
        authorization=ScopeAuthorizationService(),
        rules=RULES,
        id_generator=type("G", (), {"new_uuid": staticmethod(uuid.uuid4)})(),
    )
    from dw_kernel.errors import NotFoundError

    with pytest.raises(NotFoundError):
        await handler.handle(CASE, _context())


async def test_reading_requires_the_tender_read_scope() -> None:
    from dw_kernel.errors import PermissionDeniedError

    stranger = _context().model_copy(update={"scopes": frozenset()})
    with pytest.raises(PermissionDeniedError):
        await _handler([_package()]).handle(CASE, stranger)
