"""HTTP routes for the DW01 preparation slice (/procurement/preparation/...)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from dw_platform.application.access_context import AccessContext
from dw_tender.application.preparation.dto import PreparationCaseView
from dw_tender.application.preparation.handlers import (
    CreatePreparationCaseCommand,
    CreatePreparationCaseHandler,
    GetPreparationCaseHandler,
    ListPreparationCasesHandler,
    RunPreparationHandler,
)


class CreatePreparationCaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    description: str = ""
    source_pr_ref: str = ""
    estimated_value_minor: int = 0
    currency: str = "VND"
    deadline: str | None = None
    owner_name: str = ""
    pr_text: str


class CreatePreparationCaseResponse(BaseModel):
    case_id: uuid.UUID


class RunResponse(BaseModel):
    run_id: uuid.UUID


def build_preparation_router(
    *,
    create_case: CreatePreparationCaseHandler,
    get_case: GetPreparationCaseHandler,
    list_cases: ListPreparationCasesHandler,
    run_case: RunPreparationHandler,
    access_context_dependency: Callable[..., Any],
) -> APIRouter:
    router = APIRouter(prefix="/procurement/preparation", tags=["preparation"])
    require_context = Depends(access_context_dependency)

    @router.post("/cases", response_model=CreatePreparationCaseResponse, status_code=201)
    async def create(
        body: CreatePreparationCaseRequest,
        context: AccessContext = require_context,
    ) -> CreatePreparationCaseResponse:
        case_id = await create_case.handle(
            CreatePreparationCaseCommand(
                title=body.title,
                description=body.description,
                source_pr_ref=body.source_pr_ref,
                estimated_value_minor=body.estimated_value_minor,
                currency=body.currency,
                deadline=body.deadline,
                owner_name=body.owner_name,
                pr_text=body.pr_text,
            ),
            context,
        )
        return CreatePreparationCaseResponse(case_id=case_id)

    @router.get("/cases", response_model=list[PreparationCaseView])
    async def list_all(context: AccessContext = require_context) -> list[PreparationCaseView]:
        return await list_cases.handle(context)

    @router.get("/cases/{case_id}", response_model=PreparationCaseView)
    async def get(
        case_id: uuid.UUID, context: AccessContext = require_context
    ) -> PreparationCaseView:
        return await get_case.handle(case_id, context)

    @router.post("/cases/{case_id}/run", response_model=RunResponse, status_code=202)
    async def run(case_id: uuid.UUID, context: AccessContext = require_context) -> RunResponse:
        run_id = await run_case.handle(case_id, context)
        return RunResponse(run_id=run_id)

    return router
