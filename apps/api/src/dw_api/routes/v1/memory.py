"""Long-term memory inventory API (read-only; writes go through the policy)."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Query
from pydantic import BaseModel

from dw_api.dependencies.auth import RequireAccessContext
from dw_api.dependencies.services import RequireContainer
from dw_kernel.errors import InfrastructureError


class MemoryItemView(BaseModel):
    memory_id: uuid.UUID
    worker_id: str
    memory_type: str
    content: str
    confidence: float
    classification: str
    provenance_count: int
    valid_from: datetime
    created_by_run_id: uuid.UUID


router = APIRouter(prefix="/memory", tags=["memory"])


@router.get("/items", response_model=list[MemoryItemView])
async def list_items(
    context: RequireAccessContext,
    container: RequireContainer,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[MemoryItemView]:
    if container.memory_service is None:
        raise InfrastructureError("memory service is not configured")
    await container.authorization.require(
        context=context, action="memory.read", resource_type="memory_item"
    )
    items = await container.memory_service.list_items(context, limit=limit)
    return [
        MemoryItemView(
            memory_id=item.memory_id,
            worker_id=item.worker_id,
            memory_type=item.memory_type.value,
            content=item.content,
            confidence=item.confidence,
            classification=item.classification,
            provenance_count=len(item.provenance_refs),
            valid_from=item.valid_from,
            created_by_run_id=item.created_by_run_id,
        )
        for item in items
    ]
