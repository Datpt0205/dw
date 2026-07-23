"""Work-ops API routes (presentation layer — thin, handlers do the work).

The router factory receives handlers + an AccessContext dependency from the
composition root; it never builds adapters itself.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from dw_platform.application.access_context import AccessContext
from dw_work_ops.application.dto import MeetingView
from dw_work_ops.application.handlers import (
    CreateMeetingCommand,
    CreateMeetingHandler,
    GenerateActionsHandler,
    GetMeetingHandler,
    ListMeetingsHandler,
)


class CreateMeetingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    occurred_at: datetime
    transcript_text: str = Field(min_length=1)
    transcript_filename: str = "transcript.txt"


class CreateMeetingResponse(BaseModel):
    meeting_id: uuid.UUID


class GenerateActionsResponse(BaseModel):
    run_id: uuid.UUID


def build_work_ops_router(
    *,
    create_meeting: CreateMeetingHandler,
    get_meeting: GetMeetingHandler,
    list_meetings: ListMeetingsHandler,
    generate_actions: GenerateActionsHandler,
    access_context_dependency: Callable[..., Any],
) -> APIRouter:
    router = APIRouter(prefix="/work-ops", tags=["work-ops"])
    require_context = Depends(access_context_dependency)

    @router.post("/meetings", response_model=CreateMeetingResponse, status_code=201)
    async def create(
        body: CreateMeetingRequest, context: AccessContext = require_context
    ) -> CreateMeetingResponse:
        meeting_id = await create_meeting.handle(
            CreateMeetingCommand(
                title=body.title,
                occurred_at=body.occurred_at,
                transcript_text=body.transcript_text,
                transcript_filename=body.transcript_filename,
            ),
            context,
        )
        return CreateMeetingResponse(meeting_id=meeting_id)

    @router.get("/meetings", response_model=list[MeetingView])
    async def list_all(context: AccessContext = require_context) -> list[MeetingView]:
        return await list_meetings.handle(context)

    @router.get("/meetings/{meeting_id}", response_model=MeetingView)
    async def get(meeting_id: uuid.UUID, context: AccessContext = require_context) -> MeetingView:
        return await get_meeting.handle(meeting_id, context)

    @router.post(
        "/meetings/{meeting_id}/generate-actions",
        response_model=GenerateActionsResponse,
        status_code=202,
    )
    async def generate(
        meeting_id: uuid.UUID, context: AccessContext = require_context
    ) -> GenerateActionsResponse:
        run_id = await generate_actions.handle(meeting_id, context)
        return GenerateActionsResponse(run_id=run_id)

    return router
