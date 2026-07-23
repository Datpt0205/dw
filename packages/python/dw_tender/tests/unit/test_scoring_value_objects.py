from decimal import Decimal

import pytest

from dw_tender.domain.value_objects.scoring import (
    CriterionWeight,
    WeightedScore,
    total_weight_is_valid,
)

pytestmark = pytest.mark.unit


def test_weight_bounds() -> None:
    assert CriterionWeight(Decimal("0.3")).value == Decimal("0.3")
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        CriterionWeight(Decimal("1.1"))
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        CriterionWeight(Decimal("-0.1"))


def test_weighted_score_is_deterministic() -> None:
    score = WeightedScore(Decimal("80"), CriterionWeight(Decimal("0.25")))
    assert score.weighted_value == Decimal("20.00")


def test_raw_score_bounds() -> None:
    with pytest.raises(ValueError, match=r"\[0, 100\]"):
        WeightedScore(Decimal("101"), CriterionWeight(Decimal("0.5")))


def test_total_weight_must_sum_to_one() -> None:
    valid = [CriterionWeight(Decimal("0.6")), CriterionWeight(Decimal("0.4"))]
    invalid = [CriterionWeight(Decimal("0.6")), CriterionWeight(Decimal("0.3"))]
    assert total_weight_is_valid(valid)
    assert not total_weight_is_valid(invalid)
