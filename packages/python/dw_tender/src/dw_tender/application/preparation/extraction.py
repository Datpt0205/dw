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


class UnknownItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    question: str = Field(min_length=1, max_length=400)
    # A DRAFT the reviewer confirms/edits — never an invented fact treated as final.
    suggested_answer: str = Field(default="", max_length=600)


class PreparationExtraction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    requirements: list[ExtractedRequirement] = Field(default_factory=list)
    unknowns: list[UnknownItem] = Field(default_factory=list)
