"""HTTP routes for the DW01 preparation slice (/procurement/preparation/...)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from dw_kernel.errors import DomainError
from dw_platform.application.access_context import AccessContext
from dw_tender.application.preparation.dto import PreparationCaseView
from dw_tender.application.preparation.handlers import (
    AnswerPreparationClarificationsHandler,
    AutoPublishPreparationHandler,
    ClarificationAnswer,
    CompleteCp4Command,
    CompletePreparationCp4Handler,
    CreatePreparationCaseCommand,
    CreatePreparationCaseHandler,
    DecidePreparationCp3Handler,
    GetPreparationCaseHandler,
    ListPreparationCasesHandler,
    PreparationAuditRecorder,
    RecordPreparationPublicationHandler,
    RecordPreparationSubmissionHandler,
    RecordPublicationCommand,
    RecordSubmissionCommand,
    RejectPreparationIntakeHandler,
    RunPreparationHandler,
    SubmitAddendumCommand,
    SubmitPreparationAddendumHandler,
    VerifyPreparationIntakeHandler,
)
from dw_tender.domain.preparation.entities import BusinessDomain, ProcurementType


class CreatePreparationCaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    description: str = ""
    source_pr_ref: str = ""
    estimated_value_minor: int = 0
    currency: str = "VND"
    deadline: str | None = None
    owner_name: str = ""
    procurement_type: ProcurementType = ProcurementType.OTHER
    business_domain: BusinessDomain = BusinessDomain.GENERAL
    pr_text: str
    supplier_names: list[str] = Field(min_length=1, max_length=100)


class CreatePreparationCaseResponse(BaseModel):
    case_id: uuid.UUID


class RunResponse(BaseModel):
    run_id: uuid.UUID


class ActionResponse(BaseModel):
    status: str = "ok"


class VerifyIntakeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_reference: str = Field(min_length=1, max_length=200)
    comment: str = Field(default="", max_length=1000)


class RejectIntakeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comment: str = Field(min_length=1, max_length=2000)


class ClarificationAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clarification_id: str = Field(min_length=1, max_length=50)
    question: str = Field(min_length=1, max_length=2000)
    answer: str = Field(min_length=1, max_length=5000)
    source_note: str = Field(default="", max_length=1000)


class AnswerClarificationsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answers: list[ClarificationAnswerRequest] = Field(min_length=1, max_length=100)


class Cp3DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approve: bool
    approval_reference: str = Field(min_length=1, max_length=300)
    comment: str = Field(default="", max_length=2000)


def build_preparation_router(
    *,
    create_case: CreatePreparationCaseHandler,
    get_case: GetPreparationCaseHandler,
    list_cases: ListPreparationCasesHandler,
    run_case: RunPreparationHandler,
    verify_intake: VerifyPreparationIntakeHandler,
    reject_intake: RejectPreparationIntakeHandler,
    answer_clarifications: AnswerPreparationClarificationsHandler,
    record_publication: RecordPreparationPublicationHandler,
    auto_publish: AutoPublishPreparationHandler,
    record_submission: RecordPreparationSubmissionHandler,
    complete_cp4: CompletePreparationCp4Handler,
    submit_addendum: SubmitPreparationAddendumHandler,
    decide_cp3: DecidePreparationCp3Handler,
    audit_recorder: PreparationAuditRecorder,
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
                procurement_type=body.procurement_type,
                business_domain=body.business_domain,
                pr_text=body.pr_text,
                supplier_names=tuple(body.supplier_names),
            ),
            context,
        )
        await audit_recorder.record(context, action="preparation.case.created", case_id=case_id)
        return CreatePreparationCaseResponse(case_id=case_id)

    @router.post("/cases/upload", response_model=CreatePreparationCaseResponse, status_code=201)
    async def upload(
        context: AccessContext = require_context,
        file: UploadFile = File(...),
        title: str = Form(..., min_length=3, max_length=300),
        source_pr_ref: str = Form(..., min_length=1, max_length=200),
        estimated_value_minor: int = Form(..., gt=0),
        currency: str = Form("VND", min_length=3, max_length=3),
        deadline: str = Form(..., min_length=1, max_length=200),
        owner_name: str = Form(..., min_length=1, max_length=200),
        procurement_type: ProcurementType = Form(ProcurementType.GOODS),
        business_domain: BusinessDomain = Form(BusinessDomain.GENERAL),
        description: str = Form("", max_length=2000),
        supplier_names: str = Form(..., min_length=1, max_length=5000),
    ) -> CreatePreparationCaseResponse:
        filename = _safe_filename(file.filename or "approved-pr.txt")
        suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if suffix not in {"txt", "md"}:
            raise DomainError("DW01 intake currently accepts UTF-8 .txt or .md files")
        raw = await file.read(5 * 1024 * 1024 + 1)
        if len(raw) > 5 * 1024 * 1024:
            raise DomainError("purchase request file exceeds 5 MiB")
        try:
            pr_text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DomainError("purchase request file must use UTF-8 encoding") from exc
        suppliers = tuple(
            name.strip()
            for line in supplier_names.splitlines()
            for name in line.split(",")
            if name.strip()
        )
        case_id = await create_case.handle(
            CreatePreparationCaseCommand(
                title=title,
                description=description,
                source_pr_ref=source_pr_ref,
                estimated_value_minor=estimated_value_minor,
                currency=currency.upper(),
                deadline=deadline,
                owner_name=owner_name,
                procurement_type=procurement_type,
                business_domain=business_domain,
                pr_text=pr_text,
                pr_filename=filename,
                pr_content_type=file.content_type or "text/plain; charset=utf-8",
                supplier_names=suppliers,
            ),
            context,
        )
        await audit_recorder.record(
            context,
            action="preparation.case.created",
            case_id=case_id,
            details={
                "source_mode": "manual_upload",
                "filename": filename,
                "procurement_type": procurement_type.value,
                "business_domain": business_domain.value,
            },
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
        await audit_recorder.record(
            context,
            action="preparation.run.started",
            case_id=case_id,
            details={"run_id": str(run_id)},
        )
        return RunResponse(run_id=run_id)

    @router.post("/cases/{case_id}/verify-intake", response_model=ActionResponse)
    async def verify(
        case_id: uuid.UUID,
        body: VerifyIntakeRequest,
        context: AccessContext = require_context,
    ) -> ActionResponse:
        await verify_intake.handle(
            case_id,
            approval_reference=body.approval_reference,
            comment=body.comment,
            context=context,
        )
        await audit_recorder.record(
            context,
            action="preparation.intake.verified",
            case_id=case_id,
            details={"approval_reference": body.approval_reference},
        )
        return ActionResponse()

    @router.post("/cases/{case_id}/reject-intake", response_model=ActionResponse)
    async def reject(
        case_id: uuid.UUID,
        body: RejectIntakeRequest,
        context: AccessContext = require_context,
    ) -> ActionResponse:
        await reject_intake.handle(case_id, comment=body.comment, context=context)
        await audit_recorder.record(
            context,
            action="preparation.intake.rejected",
            case_id=case_id,
            details={"comment": body.comment.strip()},
        )
        return ActionResponse()

    @router.post("/cases/{case_id}/clarifications", response_model=ActionResponse)
    async def answer(
        case_id: uuid.UUID,
        body: AnswerClarificationsRequest,
        context: AccessContext = require_context,
    ) -> ActionResponse:
        await answer_clarifications.handle(
            case_id,
            tuple(
                ClarificationAnswer(
                    clarification_id=item.clarification_id,
                    question=item.question,
                    answer=item.answer,
                    source_note=item.source_note,
                )
                for item in body.answers
            ),
            context,
        )
        await audit_recorder.record(
            context,
            action="preparation.clarifications.answered",
            case_id=case_id,
            details={"answer_count": len(body.answers)},
        )
        return ActionResponse()

    @router.post("/cases/{case_id}/publication", response_model=ActionResponse)
    async def publish(
        case_id: uuid.UUID,
        context: AccessContext = require_context,
        file: UploadFile = File(...),
        channel: str = Form(..., min_length=1, max_length=200),
        recipient_summary: str = Form(..., min_length=1, max_length=2000),
        published_at: str = Form(..., min_length=1, max_length=100),
        external_reference: str = Form(..., min_length=1, max_length=300),
    ) -> ActionResponse:
        filename, raw = await _read_evidence_upload(file)
        await record_publication.handle(
            case_id,
            RecordPublicationCommand(
                filename=filename,
                content_type=file.content_type or "application/octet-stream",
                content=raw,
                channel=channel,
                recipient_summary=recipient_summary,
                published_at=published_at,
                external_reference=external_reference,
            ),
            context,
        )
        await audit_recorder.record(
            context,
            action="preparation.publication.recorded",
            case_id=case_id,
            details={"external_reference": external_reference, "channel": channel},
        )
        return ActionResponse()

    @router.post("/cases/{case_id}/publish-auto", response_model=ActionResponse)
    async def publish_auto(
        case_id: uuid.UUID, context: AccessContext = require_context
    ) -> ActionResponse:
        result = await auto_publish.handle(case_id, context)
        details: dict[str, object] = dict(result)
        await audit_recorder.record(
            context,
            action="preparation.publication.auto_sent",
            case_id=case_id,
            details=details,
        )
        return ActionResponse()

    @router.post("/cases/{case_id}/submissions", response_model=ActionResponse)
    async def submission(
        case_id: uuid.UUID,
        context: AccessContext = require_context,
        file: UploadFile = File(...),
        supplier_name: str = Form(..., min_length=1, max_length=300),
        received_at: str = Form(..., min_length=1, max_length=100),
        receipt_status: str = Form(..., min_length=1, max_length=50),
        external_reference: str = Form("", max_length=300),
    ) -> ActionResponse:
        filename, raw = await _read_evidence_upload(file)
        await record_submission.handle(
            case_id,
            RecordSubmissionCommand(
                filename=filename,
                content_type=file.content_type or "application/octet-stream",
                content=raw,
                supplier_name=supplier_name,
                received_at=received_at,
                receipt_status=receipt_status,
                external_reference=external_reference,
            ),
            context,
        )
        await audit_recorder.record(
            context,
            action="preparation.submission.received",
            case_id=case_id,
            details={
                "supplier_name": supplier_name,
                "receipt_status": receipt_status,
                "external_reference": external_reference,
            },
        )
        return ActionResponse()

    @router.post("/cases/{case_id}/addendum", response_model=ActionResponse)
    async def addendum(
        case_id: uuid.UUID,
        context: AccessContext = require_context,
        file: UploadFile = File(...),
        change_summary: str = Form(..., min_length=1, max_length=5000),
        impact_summary: str = Form(..., min_length=1, max_length=5000),
    ) -> ActionResponse:
        filename, raw = await _read_evidence_upload(file)
        await submit_addendum.handle(
            case_id,
            SubmitAddendumCommand(
                filename=filename,
                content_type=file.content_type or "application/octet-stream",
                content=raw,
                change_summary=change_summary,
                impact_summary=impact_summary,
            ),
            context,
        )
        await audit_recorder.record(
            context,
            action="preparation.addendum.submitted",
            case_id=case_id,
        )
        return ActionResponse()

    @router.post("/cases/{case_id}/cp3", response_model=ActionResponse)
    async def cp3(
        case_id: uuid.UUID,
        body: Cp3DecisionRequest,
        context: AccessContext = require_context,
    ) -> ActionResponse:
        await decide_cp3.handle(
            case_id,
            approve=body.approve,
            approval_reference=body.approval_reference,
            comment=body.comment,
            context=context,
        )
        await audit_recorder.record(
            context,
            action=("preparation.cp3.approved" if body.approve else "preparation.cp3.rejected"),
            case_id=case_id,
            details={"approval_reference": body.approval_reference},
        )
        return ActionResponse()

    @router.post("/cases/{case_id}/cp4", response_model=ActionResponse)
    async def cp4(
        case_id: uuid.UUID,
        context: AccessContext = require_context,
        file: UploadFile = File(...),
        opening_at: str = Form(..., min_length=1, max_length=100),
        witnesses: str = Form(..., min_length=1, max_length=2000),
        approval_reference: str = Form(..., min_length=1, max_length=300),
        comment: str = Form("", max_length=2000),
    ) -> ActionResponse:
        filename, raw = await _read_evidence_upload(file)
        witness_names = tuple(
            name.strip()
            for line in witnesses.splitlines()
            for name in line.split(",")
            if name.strip()
        )
        await complete_cp4.handle(
            case_id,
            CompleteCp4Command(
                filename=filename,
                content_type=file.content_type or "application/octet-stream",
                content=raw,
                opening_at=opening_at,
                witnesses=witness_names,
                approval_reference=approval_reference,
                comment=comment,
            ),
            context,
        )
        await audit_recorder.record(
            context,
            action="preparation.cp4.completed",
            case_id=case_id,
            details={"approval_reference": approval_reference},
        )
        return ActionResponse()

    return router


def _safe_filename(filename: str) -> str:
    safe = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not safe or safe in {".", ".."}:
        raise DomainError("invalid upload filename")
    return safe


async def _read_evidence_upload(file: UploadFile) -> tuple[str, bytes]:
    filename = _safe_filename(file.filename or "evidence.bin")
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in {"txt", "md", "pdf", "docx", "xlsx"}:
        raise DomainError("evidence accepts .txt, .md, .pdf, .docx or .xlsx")
    raw = await file.read(20 * 1024 * 1024 + 1)
    if not raw:
        raise DomainError("uploaded evidence file must not be empty")
    if len(raw) > 20 * 1024 * 1024:
        raise DomainError("uploaded evidence file exceeds 20 MiB")
    return filename, raw
