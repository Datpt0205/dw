"""Boundary DTOs (Pydantic) shared by API and workflow nodes."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from dw_work_ops.domain.entities import ActionItem, DecisionRecord, MeetingSession


class MeetingSummaryModel(BaseModel):
    """LLM output schema for SUMMARIZE_MEETING (validated, versioned by prompt)."""

    model_config = ConfigDict(extra="forbid")

    headline: str
    key_points: list[str] = Field(default_factory=list)
    language: str = "vi"


class AnalysisPoint(BaseModel):
    """One observation with its grounding quote from the transcript."""

    model_config = ConfigDict(extra="forbid")

    point: str
    evidence_quote: str | None = None


class MeetingAnalysisModel(BaseModel):
    """LLM output schema for ANALYZE_MEETING (validated, versioned by prompt)."""

    model_config = ConfigDict(extra="forbid")

    overall_assessment: str
    effectiveness_score: int = Field(ge=1, le=10)
    went_well: list[AnalysisPoint] = Field(default_factory=list)
    needs_improvement: list[AnalysisPoint] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class ExtractedDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str
    decided_by_name: str | None = None
    evidence_quote: str | None = None


class ExtractedDecisions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[ExtractedDecision] = Field(default_factory=list)


class ActionItemCandidate(BaseModel):
    """LLM output schema for EXTRACT_ACTION_ITEMS."""

    model_config = ConfigDict(extra="forbid")

    title: str
    description: str = ""
    assignee_name: str | None = None
    due_date: datetime | None = None
    due_date_explicit: bool = False
    risk_level: str = "low"
    source_quote: str | None = None


class ExtractedActions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actions: list[ActionItemCandidate] = Field(default_factory=list)


# ---------------------------------------------------------------- API views --


class ActionItemView(BaseModel):
    id: uuid.UUID
    title: str
    description: str
    status: str
    assignee_display_name: str | None
    assignee_department: str | None
    assignee_confidence: float
    due_date: datetime | None
    due_date_inferred: bool
    risk_level: str
    approval_reasons: list[str]
    external_ref: str | None = None
    external_url: str | None = None

    @classmethod
    def from_domain(
        cls, action: ActionItem, external: dict[str, str | None] | None = None
    ) -> ActionItemView:
        return cls(
            id=action.id.value,
            title=action.title,
            description=action.description,
            status=action.status.value,
            assignee_display_name=action.assignee.display_name if action.assignee else None,
            assignee_department=action.assignee.department if action.assignee else None,
            assignee_confidence=action.assignee.confidence.value if action.assignee else 0.0,
            due_date=action.due_date,
            due_date_inferred=action.due_date_inferred,
            risk_level=action.risk_level.value,
            approval_reasons=list(action.approval_reasons),
            external_ref=external.get("external_id") if external else None,
            external_url=external.get("external_url") if external else None,
        )


class DecisionView(BaseModel):
    id: uuid.UUID
    statement: str
    decided_by_name: str | None
    evidence_quote: str | None

    @classmethod
    def from_domain(cls, decision: DecisionRecord) -> DecisionView:
        return cls(
            id=decision.id,
            statement=decision.statement,
            decided_by_name=decision.decided_by_name,
            evidence_quote=decision.evidence_quote,
        )


class MeetingView(BaseModel):
    id: uuid.UUID
    title: str
    occurred_at: datetime
    status: str
    summary: dict[str, object] | None
    analysis: dict[str, object] | None = None
    last_run_id: uuid.UUID | None
    decisions: list[DecisionView] = Field(default_factory=list)
    actions: list[ActionItemView] = Field(default_factory=list)

    @classmethod
    def from_domain(
        cls,
        meeting: MeetingSession,
        decisions: list[DecisionRecord],
        actions: list[ActionItemView],
    ) -> MeetingView:
        return cls(
            id=meeting.id.value,
            title=meeting.title,
            occurred_at=meeting.occurred_at,
            status=meeting.status.value,
            summary=meeting.summary,
            analysis=meeting.analysis,
            last_run_id=meeting.last_run_id,
            decisions=[DecisionView.from_domain(d) for d in decisions],
            actions=actions,
        )
