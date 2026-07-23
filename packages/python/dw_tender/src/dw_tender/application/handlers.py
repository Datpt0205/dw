"""Tender application handlers."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass

from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.ports import WorkflowRunnerPort
from dw_kernel.errors import DomainError, NotFoundError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.ports import IdGenerator
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.entitlement import PlanEntitlementService
from dw_tender.application.dto import TenderCaseView
from dw_tender.application.ports import DocumentStoragePort, TenderUnitOfWorkFactory
from dw_tender.domain.entities import DocumentKind, TenderCase, TenderDocument
from dw_tender.domain.value_objects.ids import TenderCaseId

TENDER_FEATURE = "tender_worker"


@dataclass(frozen=True)
class DocumentUpload:
    kind: DocumentKind
    title: str
    content: str
    supplier_name: str | None = None


@dataclass(frozen=True)
class CreateTenderCaseCommand:
    title: str
    description: str
    documents: tuple[DocumentUpload, ...]


@dataclass
class CreateTenderCaseHandler:
    uow_factory: TenderUnitOfWorkFactory
    storage: DocumentStoragePort
    authorization: ScopeAuthorizationService
    entitlement: PlanEntitlementService
    id_generator: IdGenerator

    async def handle(self, cmd: CreateTenderCaseCommand, context: AccessContext) -> uuid.UUID:
        await self.authorization.require(
            context=context, action="tender.write", resource_type="tender_case"
        )
        await self.entitlement.require_feature(context, TENDER_FEATURE)

        kinds = [d.kind for d in cmd.documents]
        if DocumentKind.RFQ not in kinds:
            raise DomainError("a tender case requires an RFQ document")
        if DocumentKind.SUPPLIER_SUBMISSION not in kinds:
            raise DomainError("a tender case requires at least one supplier submission")

        case = TenderCase(
            id=TenderCaseId(self.id_generator.new_uuid()),
            tenant_id=TenantId(context.tenant_id),
            workspace_id=WorkspaceId(context.workspace_id),
            title=cmd.title,
            description=cmd.description,
            created_by=UserId(context.principal_id),
        )

        documents: list[TenderDocument] = []
        for upload in cmd.documents:
            document_id = self.id_generator.new_uuid()
            content = upload.content.encode("utf-8")
            storage_key = (
                f"{context.tenant_id}/{context.workspace_id}/tender/{case.id}/{document_id}"
            )
            await self.storage.put_object(storage_key, content, "text/plain; charset=utf-8")
            documents.append(
                TenderDocument(
                    id=document_id,
                    tenant_id=TenantId(context.tenant_id),
                    workspace_id=WorkspaceId(context.workspace_id),
                    case_id=case.id,
                    kind=upload.kind,
                    title=upload.title,
                    storage_key=storage_key,
                    content_hash=hashlib.sha256(content).hexdigest(),
                    supplier_name=upload.supplier_name,
                )
            )

        async with self.uow_factory(TenantId(context.tenant_id)) as uow:
            await uow.cases.add(case)
            for document in documents:
                await uow.documents.add(document)
            await uow.commit()
        return case.id.value


@dataclass
class GetTenderCaseHandler:
    uow_factory: TenderUnitOfWorkFactory
    authorization: ScopeAuthorizationService

    async def handle(self, case_id: uuid.UUID, context: AccessContext) -> TenderCaseView:
        await self.authorization.require(
            context=context,
            action="tender.read",
            resource_type="tender_case",
            resource_id=str(case_id),
        )
        async with self.uow_factory(TenantId(context.tenant_id)) as uow:
            case = await uow.cases.get(TenderCaseId(case_id))
            if case is None:
                raise NotFoundError("tender case not found", details={"case_id": str(case_id)})
            requirements = await uow.requirements.list_for_case(case.id)
            findings = await uow.findings.list_for_case(case.id)
            recommendation = await uow.recommendations.get_for_case(case.id)
        return TenderCaseView.from_domain(case, requirements, findings, recommendation)


@dataclass
class ListTenderCasesHandler:
    uow_factory: TenderUnitOfWorkFactory
    authorization: ScopeAuthorizationService

    async def handle(self, context: AccessContext) -> list[TenderCaseView]:
        await self.authorization.require(
            context=context, action="tender.read", resource_type="tender_case"
        )
        async with self.uow_factory(TenantId(context.tenant_id)) as uow:
            cases = await uow.cases.list_recent()
        return [TenderCaseView.from_domain(case, [], [], None) for case in cases]


@dataclass
class AnalyzeCaseHandler:
    uow_factory: TenderUnitOfWorkFactory
    workflow_runner: WorkflowRunnerPort
    authorization: ScopeAuthorizationService
    entitlement: PlanEntitlementService
    id_generator: IdGenerator
    worker_id: str = "tender"
    worker_version: str = "1.0.0"

    async def handle(self, case_id: uuid.UUID, context: AccessContext) -> uuid.UUID:
        await self.authorization.require(
            context=context,
            action="tender.write",
            resource_type="tender_case",
            resource_id=str(case_id),
        )
        await self.entitlement.require_feature(context, TENDER_FEATURE)

        run_id = self.id_generator.new_uuid()
        async with self.uow_factory(TenantId(context.tenant_id)) as uow:
            case = await uow.cases.get(TenderCaseId(case_id))
            if case is None:
                raise NotFoundError("tender case not found", details={"case_id": str(case_id)})
            case.start_analysis(run_id)
            await uow.cases.save(case)
            await uow.commit()

        run_context = RunContext(
            run_id=run_id,
            tenant_id=context.tenant_id,
            workspace_id=context.workspace_id,
            actor_id=context.principal_id,
            worker_id=self.worker_id,
            worker_version=self.worker_version,
            channel="web",
            plan_id=context.plan_id,
            roles=context.roles,
            scopes=context.scopes,
            trace_id=f"run-{run_id.hex[:12]}",
        )
        await self.workflow_runner.start(
            run_context=run_context, input_payload={"case_id": str(case_id)}
        )
        return run_id
