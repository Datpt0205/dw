"""Typed, versioned graph state for the WorkOps agent (blueprint §11.2).

Stored in checkpoints — every value must be JSON-serializable. Rich objects are
kept as validated dicts (their Pydantic schema lives in application.dto).
"""

from __future__ import annotations

from typing import Any, TypedDict

STATE_SCHEMA_VERSION = "1.0"


class WorkOpsState(TypedDict, total=False):
    schema_version: str
    meeting_id: str
    transcript_text: str
    normalized_segments: list[dict[str, Any]]  # TranscriptSegment dicts
    speaker_mapping: dict[str, str | None]
    summary: dict[str, Any] | None  # MeetingSummaryModel dict
    analysis: dict[str, Any] | None  # MeetingAnalysisModel dict
    decisions: list[dict[str, Any]]  # ExtractedDecision dicts
    action_candidates: list[dict[str, Any]]  # ActionItemCandidate dicts
    resolved_action_ids: list[str]
    approval_payload: dict[str, Any]
    approval_decision: dict[str, Any]
    dispatch_results: list[dict[str, Any]]
    memory_written: bool
    warnings: list[str]
