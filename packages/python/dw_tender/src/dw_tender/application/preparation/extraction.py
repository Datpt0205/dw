"""LLM output schema for DW01 intake requirement extraction.

The model gateway validates the model's JSON into these types before the
workflow uses it — untrusted model output never flows into the graph unchecked.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ExtractedRequirement(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str = Field(pattern=r"^REQ-\d{2}$")
    statement: str = Field(min_length=1, max_length=600)
    kind: str = Field(pattern=r"^(mandatory|informational)$")


class PreparationExtraction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    requirements: list[ExtractedRequirement] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
