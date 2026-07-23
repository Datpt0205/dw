import pytest

from dw_work_ops.domain.value_objects.confidence import Confidence, RiskLevel

pytestmark = pytest.mark.unit


def test_confidence_bounds() -> None:
    assert Confidence(0.95).value == 0.95
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        Confidence(1.5)
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        Confidence(-0.1)


def test_meets_threshold() -> None:
    threshold = Confidence(0.90)
    assert Confidence(0.90).meets(threshold)
    assert Confidence(0.95).meets(threshold)
    assert not Confidence(0.89).meets(threshold)


def test_risk_levels_are_stable_contract() -> None:
    assert {level.value for level in RiskLevel} == {"low", "medium", "high"}
