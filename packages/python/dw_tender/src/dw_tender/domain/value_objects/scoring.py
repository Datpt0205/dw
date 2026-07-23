"""Deterministic scoring primitives (blueprint §12.2).

Weights and mandatory criteria live in deterministic code/config — the LLM may
propose evidence and raw scores but never decides the formula.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class RequirementKind(StrEnum):
    MANDATORY = "mandatory"
    WEIGHTED = "weighted"
    INFORMATIONAL = "informational"


@dataclass(frozen=True, slots=True)
class CriterionWeight:
    """Normalized weight of an evaluation criterion in [0, 1]."""

    value: Decimal

    def __post_init__(self) -> None:
        if not Decimal(0) <= self.value <= Decimal(1):
            raise ValueError(f"criterion weight must be within [0, 1], got {self.value}")


@dataclass(frozen=True, slots=True)
class WeightedScore:
    """A raw score in [0, 100] combined with its criterion weight."""

    raw_score: Decimal
    weight: CriterionWeight

    def __post_init__(self) -> None:
        if not Decimal(0) <= self.raw_score <= Decimal(100):
            raise ValueError(f"raw score must be within [0, 100], got {self.raw_score}")

    @property
    def weighted_value(self) -> Decimal:
        return self.raw_score * self.weight.value


def total_weight_is_valid(weights: list[CriterionWeight]) -> bool:
    """Weighted criteria must sum to exactly 1.0 for a valid scoring config."""
    return sum((w.value for w in weights), Decimal(0)) == Decimal(1)
