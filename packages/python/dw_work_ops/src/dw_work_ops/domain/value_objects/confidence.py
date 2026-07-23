"""Confidence and risk primitives used by dispatch/approval policies (§11.3)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class Confidence:
    """Model confidence in [0, 1]; comparisons happen against policy thresholds."""

    value: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.value <= 1.0:
            raise ValueError(f"confidence must be within [0, 1], got {self.value}")

    def meets(self, threshold: Confidence) -> bool:
        return self.value >= threshold.value
