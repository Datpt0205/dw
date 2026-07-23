"""WorkOps graph nodes (blueprint §11.1).

Nodes are small, deterministic where possible, and speak only to ports. LLM
steps validate output into Pydantic schemas; assignees resolve against the
organization directory, never from model-invented identifiers.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from dw_agent_runtime.context import access_context_from_run
from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.ports import ModelRequest
from dw_kernel.errors import DomainError, NotFoundError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_knowledge.contracts import EvidenceRef
from dw_memory.contracts import MemoryType
from dw_memory.policy import MemoryCandidate
from dw_work_ops.adapters.transcript.parser import parse_transcript, resolve_speaker_names
from dw_work_ops.application.dto import (
    ActionItemCandidate,
    ExtractedActions,
    ExtractedDecisions,
    MeetingAnalysisModel,
    MeetingSummaryModel,
)
from dw_work_ops.domain.entities import (
    ActionItem,
    DecisionRecord,
    ResolvedAssignee,
)
from dw_work_ops.domain.policies import DispatchPolicyContext
from dw_work_ops.domain.value_objects.confidence import Confidence, RiskLevel
from dw_work_ops.domain.value_objects.ids import ActionItemId, MeetingId
from dw_work_ops.domain.value_objects.transcript import TranscriptSegment
from dw_work_ops.workflows.v1.services import WorkOpsWorkflowServices
from dw_work_ops.workflows.v1.state import STATE_SCHEMA_VERSION, WorkOpsState

DISPATCH_TOOL = ("task.create_external", "1.0.0")


def _run_context(config: RunnableConfig) -> RunContext:
    run_context = config.get("configurable", {}).get("run_context")
    if not isinstance(run_context, RunContext):
        raise DomainError("workflow config is missing the trusted run_context")
    return run_context


def _meeting_id(state: WorkOpsState) -> MeetingId:
    raw = state.get("meeting_id")
    if not raw:
        raise DomainError("workflow state is missing meeting_id")
    return MeetingId(uuid.UUID(raw))


class WorkOpsNodes:
    """Node implementations bound to the injected service bundle."""

    def __init__(self, services: WorkOpsWorkflowServices) -> None:
        self.services = services

    # 1 ------------------------------------------------------------------
    async def ingest_transcript(self, state: WorkOpsState, config: RunnableConfig) -> WorkOpsState:
        run_context = _run_context(config)
        meeting_id = _meeting_id(state)
        async with self.services.uow_factory(TenantId(run_context.tenant_id)) as uow:
            artifact = await uow.transcripts.get_for_meeting(meeting_id)
        if artifact is None:
            raise NotFoundError(
                "meeting has no transcript artifact",
                details={"meeting_id": str(meeting_id)},
            )
        raw = await self.services.storage.get_object(artifact.storage_key)
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "transcript_text": raw.decode("utf-8"),
        }

    # 2 ------------------------------------------------------------------
    async def normalize_transcript(
        self, state: WorkOpsState, config: RunnableConfig
    ) -> WorkOpsState:
        segments = parse_transcript(state.get("transcript_text", ""))
        if not segments:
            raise DomainError("transcript produced no segments")
        return {
            "normalized_segments": [
                {"index": s.index, "speaker": s.speaker, "text": s.text} for s in segments
            ]
        }

    # 3 ------------------------------------------------------------------
    async def resolve_speakers(self, state: WorkOpsState, config: RunnableConfig) -> WorkOpsState:
        run_context = _run_context(config)
        people = await self.services.directory.list_people(run_context.tenant_id)
        typed_segments = [
            TranscriptSegment(
                index=int(seg["index"]), speaker=str(seg["speaker"]), text=str(seg["text"])
            )
            for seg in state.get("normalized_segments", [])
        ]
        mapping = resolve_speaker_names(typed_segments, [p.display_name for p in people])
        return {"speaker_mapping": mapping}

    # 4 ------------------------------------------------------------------
    async def summarize_meeting(self, state: WorkOpsState, config: RunnableConfig) -> WorkOpsState:
        run_context = _run_context(config)
        summary = await self.services.model_gateway.generate_structured(
            ModelRequest(
                task="structured_extraction",
                prompt_id="work_ops.summarize",
                prompt_version=self.services.prompt_bundle_version,
                variables={"transcript": state.get("transcript_text", "")},
                model_profile=self.services.model_profile,
            ),
            MeetingSummaryModel,
            run_context=run_context,
        )
        return {"summary": summary.model_dump(mode="json")}

    # 4b -----------------------------------------------------------------
    async def analyze_meeting(self, state: WorkOpsState, config: RunnableConfig) -> WorkOpsState:
        """Meeting quality analysis: went well / needs improvement / next time.

        Every point must carry a verbatim transcript quote; ungrounded points
        are dropped (fail closed — same evidence discipline as tender)."""
        run_context = _run_context(config)
        analysis = await self.services.model_gateway.generate_structured(
            ModelRequest(
                task="structured_extraction",
                prompt_id="work_ops.analyze_meeting",
                prompt_version=self.services.prompt_bundle_version,
                variables={"transcript": state.get("transcript_text", "")},
                model_profile=self.services.model_profile,
            ),
            MeetingAnalysisModel,
            run_context=run_context,
        )
        transcript = state.get("transcript_text", "")
        normalized = " ".join(transcript.split()).casefold()

        def grounded(quote: str | None) -> bool:
            if not quote:
                return False
            return " ".join(quote.split()).casefold() in normalized

        cleaned = analysis.model_copy(
            update={
                "went_well": [p for p in analysis.went_well if grounded(p.evidence_quote)],
                "needs_improvement": [
                    p for p in analysis.needs_improvement if grounded(p.evidence_quote)
                ],
            }
        )
        return {"analysis": cleaned.model_dump(mode="json")}

    # 5 ------------------------------------------------------------------
    async def extract_decisions(self, state: WorkOpsState, config: RunnableConfig) -> WorkOpsState:
        run_context = _run_context(config)
        extracted = await self.services.model_gateway.generate_structured(
            ModelRequest(
                task="structured_extraction",
                prompt_id="work_ops.extract_decisions",
                prompt_version=self.services.prompt_bundle_version,
                variables={"transcript": state.get("transcript_text", "")},
                model_profile=self.services.model_profile,
            ),
            ExtractedDecisions,
            run_context=run_context,
        )
        return {"decisions": [d.model_dump(mode="json") for d in extracted.decisions]}

    # 6 ------------------------------------------------------------------
    async def extract_action_items(
        self, state: WorkOpsState, config: RunnableConfig
    ) -> WorkOpsState:
        run_context = _run_context(config)
        extracted = await self.services.model_gateway.generate_structured(
            ModelRequest(
                task="structured_extraction",
                prompt_id="work_ops.extract_actions",
                prompt_version=self.services.prompt_bundle_version,
                variables={"transcript": state.get("transcript_text", "")},
                model_profile=self.services.model_profile,
            ),
            ExtractedActions,
            run_context=run_context,
        )
        if not extracted.actions:
            return {"action_candidates": [], "warnings": ["no_action_items_extracted"]}
        return {"action_candidates": [a.model_dump(mode="json") for a in extracted.actions]}

    # 7 ------------------------------------------------------------------
    async def resolve_assignees(self, state: WorkOpsState, config: RunnableConfig) -> WorkOpsState:
        run_context = _run_context(config)
        people = await self.services.directory.list_people(run_context.tenant_id)
        by_name = {p.display_name.casefold(): p for p in people}

        enriched: list[dict[str, Any]] = []
        warnings: list[str] = list(state.get("warnings", []))
        for raw in state.get("action_candidates", []):
            candidate = dict(raw)
            name = (candidate.get("assignee_name") or "").strip()
            person = by_name.get(name.casefold())
            confidence = 0.95 if person else 0.0
            if person is None and name:
                # unique given-name suffix match, lower confidence
                suffix_matches = [p for key, p in by_name.items() if key.endswith(name.casefold())]
                if len(suffix_matches) == 1:
                    person = suffix_matches[0]
                    confidence = 0.75
            if person is None:
                warnings.append(f"assignee_unresolved:{name or 'unknown'}")
                candidate.update(
                    {
                        "resolved_person_id": None,
                        "resolved_department": None,
                        "resolved_display_name": None,
                        "resolved_confidence": 0.0,
                    }
                )
            else:
                candidate.update(
                    {
                        "resolved_person_id": str(person.person_id.value),
                        "resolved_department": person.department,
                        "resolved_display_name": person.display_name,
                        "resolved_confidence": confidence,
                    }
                )
            enriched.append(candidate)
        return {"action_candidates": enriched, "warnings": warnings}

    # 8 ------------------------------------------------------------------
    async def validate_due_dates(self, state: WorkOpsState, config: RunnableConfig) -> WorkOpsState:
        now = self.services.clock.now()
        warnings = list(state.get("warnings", []))
        updated: list[dict[str, Any]] = []
        for raw in state.get("action_candidates", []):
            candidate = dict(raw)
            due_raw = candidate.get("due_date")
            inferred = not bool(candidate.get("due_date_explicit"))
            if due_raw:
                due = datetime.fromisoformat(due_raw)
                if due.tzinfo is None:
                    due = due.replace(tzinfo=UTC)
                if due < now:
                    warnings.append(f"due_date_in_past:{candidate.get('title', '')[:40]}")
                    inferred = True
            candidate["due_date_inferred"] = inferred
            updated.append(candidate)
        return {"action_candidates": updated, "warnings": warnings}

    # 9 ------------------------------------------------------------------
    async def enrich_with_org_context(
        self, state: WorkOpsState, config: RunnableConfig
    ) -> WorkOpsState:
        run_context = _run_context(config)
        people = await self.services.directory.list_people(run_context.tenant_id)
        requester = next((p for p in people if p.person_id.value == run_context.actor_id), None)
        return {
            "approval_payload": {
                "requester_department": requester.department if requester else "general"
            }
        }

    # 10 -----------------------------------------------------------------
    async def policy_gate(self, state: WorkOpsState, config: RunnableConfig) -> WorkOpsState:
        run_context = _run_context(config)
        meeting_id = _meeting_id(state)
        requester_department = str(
            state.get("approval_payload", {}).get("requester_department", "general")
        )
        policy_ctx = DispatchPolicyContext(requester_department=requester_department)

        actions: list[ActionItem] = []
        for raw in state.get("action_candidates", []):
            candidate = ActionItemCandidate.model_validate(
                {
                    k: v
                    for k, v in raw.items()
                    if not k.startswith("resolved_") and k != "due_date_inferred"
                }
            )
            assignee = None
            if raw.get("resolved_person_id"):
                assignee = ResolvedAssignee(
                    person_id=UserId(uuid.UUID(str(raw["resolved_person_id"]))),
                    display_name=str(raw.get("resolved_display_name", "")),
                    department=str(raw.get("resolved_department", "general")),
                    confidence=Confidence(float(raw.get("resolved_confidence", 0.0))),
                )
            action = ActionItem(
                id=ActionItemId(self.services.id_generator.new_uuid()),
                tenant_id=TenantId(run_context.tenant_id),
                workspace_id=WorkspaceId(run_context.workspace_id),
                meeting_id=meeting_id,
                title=candidate.title,
                description=candidate.description,
                assignee=assignee,
                due_date=candidate.due_date,
                due_date_inferred=bool(raw.get("due_date_inferred", True)),
                risk_level=RiskLevel(candidate.risk_level),
                source_quote=candidate.source_quote,
            )
            decision = self.services.dispatch_policy.evaluate(action, policy_ctx)
            action.approval_reasons = list(decision.reasons)
            actions.append(action)

        decisions = [
            DecisionRecord(
                id=self.services.id_generator.new_uuid(),
                tenant_id=TenantId(run_context.tenant_id),
                workspace_id=WorkspaceId(run_context.workspace_id),
                meeting_id=meeting_id,
                statement=str(d.get("statement", "")),
                decided_by_name=cast(str | None, d.get("decided_by_name")),
                evidence_quote=cast(str | None, d.get("evidence_quote")),
            )
            for d in state.get("decisions", [])
        ]

        async with self.services.uow_factory(TenantId(run_context.tenant_id)) as uow:
            meeting = await uow.meetings.get(meeting_id)
            if meeting is None:
                raise NotFoundError("meeting disappeared during run")
            summary = state.get("summary") or {}
            analysis = state.get("analysis")
            meeting.mark_actions_ready(dict(summary), dict(analysis) if analysis else None)
            await uow.meetings.save(meeting)
            await uow.decisions.replace_for_meeting(meeting_id, decisions)
            await uow.actions.replace_for_meeting(meeting_id, actions)
            await uow.commit()

        approval_payload = {
            "approval_type": "work_ops.dispatch_actions",
            "reason": "Phê duyệt danh sách action item trước khi giao việc",
            "meeting_id": str(meeting_id),
            "requester_department": requester_department,
            "actions": [
                {
                    "action_id": str(a.id.value),
                    "title": a.title,
                    "assignee": a.assignee.display_name if a.assignee else None,
                    "department": a.assignee.department if a.assignee else None,
                    "due_date": a.due_date.isoformat() if a.due_date else None,
                    "approval_reasons": a.approval_reasons,
                }
                for a in actions
            ],
        }
        return {
            "resolved_action_ids": [str(a.id.value) for a in actions],
            "approval_payload": approval_payload,
        }

    # 11 -----------------------------------------------------------------
    async def human_review(self, state: WorkOpsState, config: RunnableConfig) -> WorkOpsState:
        decision: dict[str, Any] = interrupt(state.get("approval_payload", {}))
        return {"approval_decision": dict(decision)}

    # 12 -----------------------------------------------------------------
    async def dispatch_tasks(self, state: WorkOpsState, config: RunnableConfig) -> WorkOpsState:
        run_context = _run_context(config)
        decision = state.get("approval_decision", {})
        approved = bool(decision.get("approved"))
        approved_ids = decision.get("approved_action_ids")
        results: list[dict[str, Any]] = []

        async with self.services.uow_factory(TenantId(run_context.tenant_id)) as uow:
            for action_id_raw in state.get("resolved_action_ids", []):
                action = await uow.actions.get(ActionItemId(uuid.UUID(action_id_raw)))
                if action is None:
                    continue
                selected = approved and (approved_ids is None or action_id_raw in approved_ids)
                if not selected:
                    action.reject()
                    await uow.actions.save(action)
                    results.append({"action_id": action_id_raw, "status": "rejected"})
                    continue
                if action.assignee is None:
                    results.append({"action_id": action_id_raw, "status": "skipped_unresolved"})
                    continue

                action.approve()
                await uow.actions.save(action)

                tool_name, tool_version = DISPATCH_TOOL
                idempotency_key = f"{run_context.tenant_id}:{action_id_raw}:mock:{tool_version}"
                output = await self.services.tool_executor.execute(
                    name=tool_name,
                    version=tool_version,
                    raw_input={
                        "action_id": action_id_raw,
                        "title": action.title,
                        "description": action.description,
                        "assignee_person_id": str(action.assignee.person_id.value),
                        "assignee_display_name": action.assignee.display_name,
                        "due_date": action.due_date.isoformat() if action.due_date else None,
                    },
                    run_context=run_context,
                    idempotency_key=idempotency_key,
                    approved=True,  # the human just approved via the interrupt
                )
                payload = output.model_dump(mode="json")
                action.mark_dispatched()
                await uow.actions.save(action)
                await uow.actions.record_external_task(
                    action.id,
                    connector=str(payload.get("connector", "mock")),
                    connector_version=str(payload.get("connector_version", tool_version)),
                    external_id=str(payload.get("external_id", "")),
                    external_url=cast(str | None, payload.get("external_url")),
                )
                results.append(
                    {
                        "action_id": action_id_raw,
                        "status": "dispatched",
                        "external_id": payload.get("external_id"),
                    }
                )
            await uow.commit()
        return {"dispatch_results": results}

    # 13 -----------------------------------------------------------------
    async def track_and_follow_up(
        self, state: WorkOpsState, config: RunnableConfig
    ) -> WorkOpsState:
        warnings = list(state.get("warnings", []))
        for result in state.get("dispatch_results", []):
            if result.get("status") == "dispatched":
                continue
            warnings.append(f"follow_up_needed:{result.get('action_id')}")
        return {"warnings": warnings}

    # 14 -----------------------------------------------------------------
    async def close_and_write_memory(
        self, state: WorkOpsState, config: RunnableConfig
    ) -> WorkOpsState:
        run_context = _run_context(config)
        meeting_id = _meeting_id(state)

        async with self.services.uow_factory(TenantId(run_context.tenant_id)) as uow:
            meeting = await uow.meetings.get(meeting_id)
            artifact = await uow.transcripts.get_for_meeting(meeting_id)
            if meeting is not None:
                meeting.complete()
                await uow.meetings.save(meeting)
            await uow.commit()

        memory_written = False
        summary = state.get("summary") or {}
        dispatched = [
            r for r in state.get("dispatch_results", []) if r.get("status") == "dispatched"
        ]
        if artifact is not None and summary.get("headline"):
            evidence = EvidenceRef(
                evidence_id=self.services.id_generator.new_uuid(),
                source_document_id=artifact.id.value,
                source_version="1",
                quote=str(summary.get("headline", ""))[:280],
                relevance_score=1.0,
                classification="internal",
                provenance_hash=artifact.content_hash,
            )
            result = await self.services.memory_service.propose(
                MemoryCandidate(
                    worker_id=run_context.worker_id,
                    memory_type=MemoryType.EPISODIC,
                    content=(
                        f"Cuộc họp '{summary.get('headline')}': "
                        f"{len(state.get('decisions', []))} quyết định, "
                        f"{len(dispatched)} action đã giao."
                    ),
                    provenance_refs=(evidence,),
                    confidence=0.9,
                ),
                access_context_from_run(run_context),
                created_by_run_id=run_context.run_id,
            )
            memory_written = result.item is not None
        return {"memory_written": memory_written}
