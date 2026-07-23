"""Memory service: candidate → policy decision → (maybe) stored item."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_kernel.ports import IdGenerator, UtcClock
from dw_memory import tables
from dw_memory.contracts import MEMORY_SCHEMA_VERSION, MemoryItem, WriteDecision
from dw_memory.policy import MemoryCandidate, MemoryWritePolicy, PolicyOutcome
from dw_platform.application.access_context import AccessContext

_SET_TENANT = text("SELECT set_config('app.tenant_id', :tenant_id, true)")


@dataclass(frozen=True)
class ProposalResult:
    candidate_id: uuid.UUID
    outcome: PolicyOutcome
    item: MemoryItem | None


@dataclass
class MemoryService:
    session_factory: async_sessionmaker[AsyncSession]
    policy: MemoryWritePolicy
    clock: UtcClock
    id_generator: IdGenerator

    async def propose(
        self,
        candidate: MemoryCandidate,
        context: AccessContext,
        *,
        created_by_run_id: uuid.UUID,
    ) -> ProposalResult:
        outcome = self.policy.evaluate(candidate)
        candidate_id = self.id_generator.new_uuid()
        now = self.clock.now()

        item: MemoryItem | None = None
        if outcome.decision is WriteDecision.AUTO_WRITE:
            item = MemoryItem(
                memory_id=self.id_generator.new_uuid(),
                tenant_id=context.tenant_id,
                workspace_id=context.workspace_id,
                worker_id=candidate.worker_id,
                memory_type=candidate.memory_type,
                subject_refs=candidate.subject_refs,
                content=candidate.content,
                structured_facts=dict(candidate.structured_facts),
                provenance_refs=candidate.provenance_refs,
                confidence=candidate.confidence,
                classification=candidate.classification,
                valid_from=now,
                retention_policy="default",
                memory_schema_version=MEMORY_SCHEMA_VERSION,
                created_by_run_id=created_by_run_id,
            )

        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"tenant_id": str(context.tenant_id)})
            await session.execute(
                sa.insert(tables.write_candidates).values(
                    id=candidate_id,
                    tenant_id=context.tenant_id,
                    workspace_id=context.workspace_id,
                    worker_id=candidate.worker_id,
                    memory_type=candidate.memory_type.value,
                    content=candidate.content,
                    structured_facts=dict(candidate.structured_facts),
                    provenance_refs=[
                        ref.model_dump(mode="json") for ref in candidate.provenance_refs
                    ],
                    confidence=candidate.confidence,
                    classification=candidate.classification,
                    decision=outcome.decision.value,
                    memory_id=item.memory_id if item else None,
                    created_by_run_id=created_by_run_id,
                    created_at=now,
                )
            )
            if item is not None:
                await session.execute(
                    sa.insert(tables.items).values(
                        memory_id=item.memory_id,
                        tenant_id=item.tenant_id,
                        workspace_id=item.workspace_id,
                        worker_id=item.worker_id,
                        memory_type=item.memory_type.value,
                        subject_refs=list(item.subject_refs),
                        content=item.content,
                        structured_facts=dict(item.structured_facts),
                        provenance_refs=[
                            ref.model_dump(mode="json") for ref in item.provenance_refs
                        ],
                        confidence=item.confidence,
                        classification=item.classification,
                        valid_from=item.valid_from,
                        valid_until=item.valid_until,
                        retention_policy=item.retention_policy,
                        memory_schema_version=item.memory_schema_version,
                        created_by_run_id=item.created_by_run_id,
                        created_at=now,
                    )
                )
        return ProposalResult(candidate_id=candidate_id, outcome=outcome, item=item)
