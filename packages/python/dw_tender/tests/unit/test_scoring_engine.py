import uuid
from decimal import Decimal

import pytest

from dw_kernel.ids import TenantId, WorkspaceId
from dw_tender.domain.entities import ComplianceFinding, FindingStatus, Requirement
from dw_tender.domain.exceptions import InvalidScoringConfigError
from dw_tender.domain.services.scoring_engine import ScoringEngine, ScoringPolicy
from dw_tender.domain.value_objects.ids import RequirementId, TenderCaseId
from dw_tender.domain.value_objects.scoring import RequirementKind

pytestmark = pytest.mark.unit

TENANT = TenantId(uuid.uuid4())
WORKSPACE = WorkspaceId(uuid.uuid4())
CASE = TenderCaseId(uuid.uuid4())

SUPPLIER_A = "Công ty TNHH Thiết bị Việt"
SUPPLIER_B = "Công ty CP Vật tư Miền Nam"

EVIDENCE: tuple[dict[str, object], ...] = ({"quote": "trích dẫn", "provenance_hash": "a" * 64},)


def requirement(code: str, kind: RequirementKind, weight: str = "0") -> Requirement:
    return Requirement(
        id=RequirementId(uuid.uuid4()),
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        case_id=CASE,
        code=code,
        statement=f"Yêu cầu {code}",
        kind=kind,
        weight=Decimal(weight),
    )


def finding(
    supplier: str,
    code: str,
    status: FindingStatus,
    raw: str,
    evidence: tuple[dict[str, object], ...] = EVIDENCE,
) -> ComplianceFinding:
    return ComplianceFinding(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        case_id=CASE,
        requirement_code=code,
        supplier_name=supplier,
        status=status,
        raw_score=Decimal(raw),
        evidence=evidence,
    )


REQUIREMENTS = [
    requirement("REQ-01", RequirementKind.MANDATORY),
    requirement("REQ-02", RequirementKind.MANDATORY),
    requirement("REQ-03", RequirementKind.WEIGHTED, "0.6"),
    requirement("REQ-04", RequirementKind.WEIGHTED, "0.4"),
]

GOLDEN_FINDINGS = [
    finding(SUPPLIER_A, "REQ-01", FindingStatus.COMPLIANT, "100"),
    finding(SUPPLIER_A, "REQ-02", FindingStatus.COMPLIANT, "100"),
    finding(SUPPLIER_A, "REQ-03", FindingStatus.COMPLIANT, "85"),
    finding(SUPPLIER_A, "REQ-04", FindingStatus.COMPLIANT, "90"),
    finding(SUPPLIER_B, "REQ-01", FindingStatus.COMPLIANT, "100"),
    finding(SUPPLIER_B, "REQ-02", FindingStatus.NON_COMPLIANT, "0"),
    finding(SUPPLIER_B, "REQ-03", FindingStatus.COMPLIANT, "90"),
    finding(SUPPLIER_B, "REQ-04", FindingStatus.COMPLIANT, "60"),
]


def make_engine() -> ScoringEngine:
    return ScoringEngine(ScoringPolicy(policy_version="1.0.0"))


def test_golden_totals_are_exact() -> None:
    """A: 85*0.6 + 90*0.4 = 87.00 · B: 90*0.6 + 60*0.4 = 78.00 (nhưng loại)."""
    outcome = make_engine().evaluate(REQUIREMENTS, GOLDEN_FINDINGS, SUPPLIER_A)
    by_name = {s.supplier_name: s for s in outcome.scores}
    assert by_name[SUPPLIER_A].total_score == Decimal("87.00")
    assert by_name[SUPPLIER_A].eligible is True
    assert by_name[SUPPLIER_B].total_score == Decimal("78.00")
    assert by_name[SUPPLIER_B].mandatory_passed is False
    assert by_name[SUPPLIER_B].eligible is False, "mandatory fail must disqualify"
    assert outcome.top_supplier == SUPPLIER_A
    assert outcome.gate_passed is True


def test_deterministic_same_input_same_output() -> None:
    engine = make_engine()
    first = engine.evaluate(REQUIREMENTS, GOLDEN_FINDINGS, SUPPLIER_A)
    second = engine.evaluate(REQUIREMENTS, GOLDEN_FINDINGS, SUPPLIER_A)
    assert first == second


def test_mandatory_without_evidence_fails_closed() -> None:
    """Compliant claim + NO evidence → mandatory not satisfied (§12.2)."""
    findings = [
        finding(SUPPLIER_A, "REQ-01", FindingStatus.COMPLIANT, "100", evidence=()),
        finding(SUPPLIER_A, "REQ-02", FindingStatus.COMPLIANT, "100"),
        finding(SUPPLIER_A, "REQ-03", FindingStatus.COMPLIANT, "85"),
        finding(SUPPLIER_A, "REQ-04", FindingStatus.COMPLIANT, "90"),
    ]
    score = make_engine().score_supplier(SUPPLIER_A, REQUIREMENTS, findings)
    assert score.mandatory_passed is False
    assert "REQ-01:missing_evidence" in score.violations
    assert score.eligible is False


def test_gate_overrides_wrong_draft_recommendation() -> None:
    """Model đề xuất supplier bị loại → gate phát hiện mismatch."""
    outcome = make_engine().evaluate(REQUIREMENTS, GOLDEN_FINDINGS, SUPPLIER_B)
    assert outcome.top_supplier == SUPPLIER_A
    assert outcome.gate_passed is False
    assert any(v.startswith("recommendation_mismatch") for v in outcome.violations)


def test_no_eligible_supplier() -> None:
    findings = [
        finding(SUPPLIER_A, "REQ-02", FindingStatus.NON_COMPLIANT, "0"),
        finding(SUPPLIER_A, "REQ-03", FindingStatus.COMPLIANT, "50"),
    ]
    outcome = make_engine().evaluate(REQUIREMENTS, findings, SUPPLIER_A)
    assert outcome.top_supplier is None
    assert "no_eligible_supplier" in outcome.violations


def test_invalid_weights_rejected() -> None:
    bad = [
        requirement("REQ-01", RequirementKind.MANDATORY),
        requirement("REQ-03", RequirementKind.WEIGHTED, "0.6"),
        requirement("REQ-04", RequirementKind.WEIGHTED, "0.3"),
    ]
    with pytest.raises(InvalidScoringConfigError, match="sum to 1"):
        make_engine().validate_requirements(bad)


def test_below_min_total_not_eligible() -> None:
    findings = [
        finding(SUPPLIER_A, "REQ-01", FindingStatus.COMPLIANT, "100"),
        finding(SUPPLIER_A, "REQ-02", FindingStatus.COMPLIANT, "100"),
        finding(SUPPLIER_A, "REQ-03", FindingStatus.COMPLIANT, "50"),
        finding(SUPPLIER_A, "REQ-04", FindingStatus.COMPLIANT, "50"),
    ]
    score = make_engine().score_supplier(SUPPLIER_A, REQUIREMENTS, findings)
    assert score.total_score == Decimal("50.00")
    assert score.eligible is False
