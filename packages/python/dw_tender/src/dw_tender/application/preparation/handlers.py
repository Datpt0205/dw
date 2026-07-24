"""DW01 preparation application handlers (create / get / list / run)."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass

from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.ports import WorkflowRunnerPort
from dw_kernel.errors import NotFoundError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.ports import IdGenerator
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.entitlement import PlanEntitlementService
from dw_tender.application.preparation.dto import PreparationCaseView
from dw_tender.application.preparation.ports import PreparationUnitOfWorkFactory
from dw_tender.application.ports import DocumentStoragePort
from dw_tender.domain.preparation.entities import (
    DocumentKind,
    PreparationCase,
    PreparationDocument,
)
from dw_tender.domain.value_objects.ids import (
    PreparationCaseId,
    PreparationDocumentId,
)

TENDER_FEATURE = "tender_worker"


@dataclass(frozen=True)
class CreatePreparationCaseCommand:
    title: str
    description: str
    source_pr_ref: str
    estimated_value_minor: int
    currency: str
    deadline: str | None
    owner_name: str
    pr_text: str


@dataclass
class CreatePreparationCaseHandler:
    uow_factory: PreparationUnitOfWorkFactory
    storage: DocumentStoragePort
    authorization: ScopeAuthorizationService
    entitlement: PlanEntitlementService
    id_generator: IdGenerator

    async def handle(self, command: CreatePreparationCaseCommand, context: AccessContext) -> uuid.UUID:
        await self.authorization.require(
            context=context, action="tender.write", resource_type="preparation_case"
        )
        await self.entitlement.require_feature(context, TENDER_FEATURE)

        case = PreparationCase(
            id=PreparationCaseId(self.id_generator.new_uuid()),
            tenant_id=TenantId(context.tenant_id),
            workspace_id=WorkspaceId(context.workspace_id),
            title=command.title,
            created_by=UserId(context.principal_id),
            source_pr_ref=command.source_pr_ref,
            description=command.description,
            estimated_value_minor=command.estimated_value_minor,
            currency=command.currency,
            deadline=command.deadline,
            owner_name=command.owner_name,
        )
        case.mark_intake_ready()

        pr_bytes = command.pr_text.encode("utf-8")
        storage_key = (
            f"{context.tenant_id}/{context.workspace_id}/preparation/{case.id.value}/approved_pr"
        )
        await self.storage.put_object(storage_key, pr_bytes, "text/plain")
        document = PreparationDocument(
            id=PreparationDocumentId(self.id_generator.new_uuid()),
            tenant_id=TenantId(context.tenant_id),
            workspace_id=WorkspaceId(context.workspace_id),
            case_id=case.id,
            kind=DocumentKind.APPROVED_PR,
            title="Phiếu yêu cầu mua sắm (PR)",
            storage_key=storage_key,
            content_hash=hashlib.sha256(pr_bytes).hexdigest(),
            uploaded_by=UserId(context.principal_id),
        )
        async with self.uow_factory(TenantId(context.tenant_id)) as uow:
            await uow.cases.add(case)
            await uow.documents.add(document)
            await uow.commit()
        return case.id.value


@dataclass
class GetPreparationCaseHandler:
    uow_factory: PreparationUnitOfWorkFactory
    authorization: ScopeAuthorizationService

    async def handle(self, case_id: uuid.UUID, context: AccessContext) -> PreparationCaseView:
        await self.authorization.require(
            context=context,
            action="tender.read",
            resource_type="preparation_case",
            resource_id=str(case_id),
        )
        async with self.uow_factory(TenantId(context.tenant_id)) as uow:
            case = await uow.cases.get(PreparationCaseId(case_id))
            if case is None:
                raise NotFoundError("preparation case not found", details={"case_id": str(case_id)})
            artifacts = await uow.artifacts.list_for_case(case.id)
        return PreparationCaseView.from_domain(case, artifacts)


@dataclass
class ListPreparationCasesHandler:
    uow_factory: PreparationUnitOfWorkFactory
    authorization: ScopeAuthorizationService

    async def handle(self, context: AccessContext) -> list[PreparationCaseView]:
        await self.authorization.require(
            context=context, action="tender.read", resource_type="preparation_case"
        )
        async with self.uow_factory(TenantId(context.tenant_id)) as uow:
            cases = await uow.cases.list_recent()
        return [PreparationCaseView.from_domain(case) for case in cases]


@dataclass
class RunPreparationHandler:
    uow_factory: PreparationUnitOfWorkFactory
    workflow_runner: WorkflowRunnerPort
    authorization: ScopeAuthorizationService
    entitlement: PlanEntitlementService
    id_generator: IdGenerator
    worker_id: str = "preparation"
    worker_version: str = "1.0.0"

    async def handle(self, case_id: uuid.UUID, context: AccessContext) -> uuid.UUID:
        await self.authorization.require(
            context=context,
            action="tender.write",
            resource_type="preparation_case",
            resource_id=str(case_id),
        )
        await self.entitlement.require_feature(context, TENDER_FEATURE)

        run_id = self.id_generator.new_uuid()
        async with self.uow_factory(TenantId(context.tenant_id)) as uow:
            case = await uow.cases.get(PreparationCaseId(case_id))
            if case is None:
                raise NotFoundError("preparation case not found", details={"case_id": str(case_id)})
            case.start_run(run_id)
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
