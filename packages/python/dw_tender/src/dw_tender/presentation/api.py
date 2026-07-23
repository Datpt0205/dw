"""Procurement API routes (presentation layer)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from dw_platform.application.access_context import AccessContext
from dw_tender.application.dto import TenderCaseView
from dw_tender.application.handlers import (
    AnalyzeCaseHandler,
    CreateTenderCaseCommand,
    CreateTenderCaseHandler,
    DocumentUpload,
    GetTenderCaseHandler,
    ListTenderCasesHandler,
)
from dw_tender.domain.entities import DocumentKind


class DocumentUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: DocumentKind
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1)
    supplier_name: str | None = None


class CreateCaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    description: str = ""
    documents: list[DocumentUploadRequest] = Field(min_length=1)


class CreateCaseResponse(BaseModel):
    case_id: uuid.UUID


class AnalyzeResponse(BaseModel):
    run_id: uuid.UUID


def build_procurement_router(
    *,
    create_case: CreateTenderCaseHandler,
    get_case: GetTenderCaseHandler,
    list_cases: ListTenderCasesHandler,
    analyze_case: AnalyzeCaseHandler,
    access_context_dependency: Callable[..., Any],
) -> APIRouter:
    router = APIRouter(prefix="/procurement", tags=["procurement"])
    require_context = Depends(access_context_dependency)

    @router.post("/cases", response_model=CreateCaseResponse, status_code=201)
    async def create(
        body: CreateCaseRequest, context: AccessContext = require_context
    ) -> CreateCaseResponse:
        case_id = await create_case.handle(
            CreateTenderCaseCommand(
                title=body.title,
                description=body.description,
                documents=tuple(
                    DocumentUpload(
                        kind=doc.kind,
                        title=doc.title,
                        content=doc.content,
                        supplier_name=doc.supplier_name,
                    )
                    for doc in body.documents
                ),
            ),
            context,
        )
        return CreateCaseResponse(case_id=case_id)

    @router.get("/cases", response_model=list[TenderCaseView])
    async def list_all(context: AccessContext = require_context) -> list[TenderCaseView]:
        return await list_cases.handle(context)

    @router.get("/cases/{case_id}", response_model=TenderCaseView)
    async def get(case_id: uuid.UUID, context: AccessContext = require_context) -> TenderCaseView:
        return await get_case.handle(case_id, context)

    @router.post("/cases/{case_id}/analyze", response_model=AnalyzeResponse, status_code=202)
    async def analyze(
        case_id: uuid.UUID, context: AccessContext = require_context
    ) -> AnalyzeResponse:
        run_id = await analyze_case.handle(case_id, context)
        return AnalyzeResponse(run_id=run_id)

    return router
