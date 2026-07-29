"""LLM output schemas for DW01 solicitation + evaluation-criteria drafting.

Model JSON is validated into these types; weights are re-checked (must sum to
100) before use, with a deterministic rule-pack fallback when the model is
absent, errors, or returns inconsistent weights.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SolicitationDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    scope: str = Field(min_length=1, max_length=1200)
    technical_requirements: list[str] = Field(default_factory=list)


class WeightedCriterion(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str = Field(pattern=r"^W\d{1,2}$")
    text: str = Field(min_length=1, max_length=200)
    weight: int = Field(ge=0, le=100)


class CriteriaDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    weighted: list[WeightedCriterion] = Field(default_factory=list)

    def weights_valid(self) -> bool:
        return bool(self.weighted) and sum(c.weight for c in self.weighted) == 100
