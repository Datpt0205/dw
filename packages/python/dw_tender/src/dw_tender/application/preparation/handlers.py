"""DW01 preparation application handlers (create / get / list / run)."""

from __future__ import annotations

import contextlib
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.ports import WorkflowRunnerPort
from dw_kernel.errors import ConflictError, DomainError, NotFoundError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.ports import IdGenerator, UtcClock
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.entitlement import PlanEntitlementService
from dw_platform.application.ports import PlatformUnitOfWorkFactory
from dw_platform.domain.audit import AuditEvent
from dw_tender.application.ports import DocumentStoragePort, EmailPublisherPort
from dw_tender.application.preparation.dto import PreparationCaseView
from dw_tender.application.preparation.intake_quota_guard import IntakeQuotaGuard
from dw_tender.application.preparation.ports import (
    PreparationUnitOfWork,
    PreparationUnitOfWorkFactory,
)
from dw_tender.application.preparation.rework import ReworkSupportRules
from dw_tender.application.preparation.rework_guard import ReworkGuard
from dw_tender.application.preparation.rework_recording import record_rework_event
from dw_tender.application.preparation.rules import ProcurementRules
from dw_tender.domain.preparation.entities import (
    ArtifactStatus,
    ArtifactType,
    BusinessDomain,
    CaseState,
    DocumentKind,
    PreparationArtifact,
    PreparationCase,
    PreparationDocument,
    ProcurementType,
)
from dw_tender.domain.preparation.notifications import (
    IntakeNotificationJob,
    IntakeNotificationType,
)
from dw_tender.domain.preparation.rework import ReworkCheckpoint
from dw_tender.domain.value_objects.ids import (
    ArtifactId,
    PreparationCaseId,
    PreparationDocumentId,
)

TENDER_FEATURE = "tender_worker"


@dataclass
class PreparationAuditRecorder:
    uow_factory: PlatformUnitOfWorkFactory
    clock: UtcClock
    id_generator: IdGenerator

    async def record(
        self,
        context: AccessContext,
        *,
        action: str,
        case_id: uuid.UUID,
        details: dict[str, object] | None = None,
    ) -> None:
        async with self.uow_factory(context) as uow:
            await uow.audit.append(
                AuditEvent(
                    id=self.id_generator.new_uuid(),
                    tenant_id=TenantId(context.tenant_id),
                    workspace_id=WorkspaceId(context.workspace_id),
                    actor_id=UserId(context.principal_id),
                    action=action,
                    resource_type="preparation_case",
                    resource_id=str(case_id),
                    occurred_at=self.clock.now().astimezone(UTC),
                    policy_decision="allow",
                    details=details or {},
                )
            )
            await uow.commit()


@dataclass(frozen=True)
class CreatePreparationCaseCommand:
    title: str
    description: str
    source_pr_ref: str
    estimated_value_minor: int
    currency: str
    deadline: str | None
    owner_name: str
    procurement_type: ProcurementType
    business_domain: BusinessDomain
    pr_text: str
    pr_filename: str = "approved-pr.txt"
    pr_content_type: str = "text/plain; charset=utf-8"
    supplier_names: tuple[str, ...] = ()


@dataclass
class CreatePreparationCaseHandler:
    uow_factory: PreparationUnitOfWorkFactory
    storage: DocumentStoragePort
    authorization: ScopeAuthorizationService
    entitlement: PlanEntitlementService
    id_generator: IdGenerator
    clock: UtcClock
    reminder_seconds: int = 5
    rework_guard: ReworkGuard | None = None
    intake_quota_guard: IntakeQuotaGuard | None = None

    async def handle(
        self, command: CreatePreparationCaseCommand, context: AccessContext
    ) -> uuid.UUID:
        await self.authorization.require(
            context=context, action="tender.write", resource_type="preparation_case"
        )
        await self.entitlement.require_feature(context, TENDER_FEATURE)
        if self.rework_guard is not None:
            await self.rework_guard.require_not_blocked(context)
        # Quota is checked after rework on purpose: someone whose work keeps
        # coming back should hear about support first, not about a count.
        if self.intake_quota_guard is not None:
            await self.intake_quota_guard.require_not_blocked(context)

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
            procurement_type=command.procurement_type,
            business_domain=command.business_domain,
        )
        pr_bytes = command.pr_text.encode("utf-8")
        if not pr_bytes:
            raise DomainError("purchase request file must not be empty")
        if len(pr_bytes) > 5 * 1024 * 1024:
            raise DomainError("purchase request file exceeds 5 MiB")
        suppliers = tuple(
            dict.fromkeys(name.strip() for name in command.supplier_names if name.strip())
        )
        if not suppliers:
            raise DomainError("at least one supplier candidate is required")
        storage_key = (
            f"{context.tenant_id}/{context.workspace_id}/preparation/{case.id.value}/"
            f"sources/{command.pr_filename}"
        )
        await self.storage.put_object(storage_key, pr_bytes, command.pr_content_type)
        document = PreparationDocument(
            id=PreparationDocumentId(self.id_generator.new_uuid()),
            tenant_id=TenantId(context.tenant_id),
            workspace_id=WorkspaceId(context.workspace_id),
            case_id=case.id,
            kind=DocumentKind.APPROVED_PR,
            title="Phiếu yêu cầu mua sắm (PR)",
            filename=command.pr_filename,
            content_type=command.pr_content_type,
            size_bytes=len(pr_bytes),
            storage_key=storage_key,
            content_hash=hashlib.sha256(pr_bytes).hexdigest(),
            uploaded_by=UserId(context.principal_id),
        )
        supplier_content: dict[str, Any] = {
            "source": "manual_entry",
            "suppliers": [{"name": name} for name in suppliers],
        }
        supplier_artifact = PreparationArtifact(
            id=ArtifactId(self.id_generator.new_uuid()),
            tenant_id=case.tenant_id,
            workspace_id=case.workspace_id,
            case_id=case.id,
            artifact_type=ArtifactType.SUPPLIER_INPUT,
            schema_version="1.0",
            artifact_version=1,
            status=ArtifactStatus.DRAFT,
            content=supplier_content,
            created_by=UserId(context.principal_id),
            content_hash=_content_hash(supplier_content),
        )
        async with self.uow_factory(TenantId(context.tenant_id)) as uow:
            # Intake verification goes to someone OTHER than the person who
            # filed it. A requester creating a case lands on the procurement
            # specialist; the specialist filing one himself goes up to the head
            # of procurement rather than back down to the requester.
            creator = UserId(context.principal_id)
            approver = await uow.notifications.find_recipient_for_role("approver", exclude=creator)
            if approver is None:
                approver = await uow.notifications.find_recipient_for_role(
                    "procurement_head", exclude=creator
                )
            escalation_owner = await uow.notifications.find_recipient_for_role("platform_admin")
            if approver is None:
                raise DomainError("DW01 intake requires an approver membership")
            if escalation_owner is None:
                raise DomainError("DW01 intake requires a platform_admin escalation owner")
            await uow.cases.add(case)
            await uow.documents.add(document)
            await uow.artifacts.add(supplier_artifact)
            now = self.clock.now().astimezone(UTC)
            notification_payload: dict[str, object] = {
                "title": case.title,
                "source_pr_ref": case.source_pr_ref,
                "owner_name": case.owner_name,
                "procurement_type": case.procurement_type.value,
                "business_domain": case.business_domain.value,
                "estimated_value_minor": case.estimated_value_minor,
                "currency": case.currency,
            }
            await uow.notifications.enqueue(
                IntakeNotificationJob(
                    id=self.id_generator.new_uuid(),
                    tenant_id=case.tenant_id,
                    workspace_id=case.workspace_id,
                    case_id=case.id,
                    event_type=IntakeNotificationType.APPROVAL_REQUESTED,
                    recipient_user_id=approver,
                    due_at=now,
                    idempotency_key=f"dw01:{case.id.value}:intake:requested",
                    payload=notification_payload,
                )
            )
            await uow.notifications.enqueue(
                IntakeNotificationJob(
                    id=self.id_generator.new_uuid(),
                    tenant_id=case.tenant_id,
                    workspace_id=case.workspace_id,
                    case_id=case.id,
                    event_type=IntakeNotificationType.APPROVAL_ESCALATED,
                    recipient_user_id=escalation_owner,
                    due_at=now + timedelta(seconds=self.reminder_seconds),
                    idempotency_key=f"dw01:{case.id.value}:intake:escalated",
                    payload=notification_payload,
                )
            )
            await uow.commit()
        return case.id.value


@dataclass
class VerifyPreparationIntakeHandler:
    uow_factory: PreparationUnitOfWorkFactory
    authorization: ScopeAuthorizationService
    clock: UtcClock
    id_generator: IdGenerator
    # Auto-start DW01 right after a successful verification (attributed to the
    # case owner). Optional so tests/callers that don't wire it keep working.
    run_case: RunPreparationHandler | None = None

    async def handle(
        self,
        case_id: uuid.UUID,
        *,
        approval_reference: str,
        comment: str,
        context: AccessContext,
    ) -> None:
        await self.authorization.require(
            context=context,
            action="approvals.decide",
            resource_type="preparation_intake",
            resource_id=str(case_id),
        )
        if not approval_reference.strip():
            raise DomainError("approval reference must not be blank")
        async with self.uow_factory(TenantId(context.tenant_id)) as uow:
            case = await uow.cases.get(PreparationCaseId(case_id))
            if case is None:
                raise NotFoundError("preparation case not found")
            if case.created_by.value == context.principal_id:
                raise ConflictError("case creator cannot verify their own intake")
            documents = await uow.documents.list_for_case(case.id)
            if not documents:
                raise DomainError("intake has no source document")
            verified_at = self.clock.now().astimezone(UTC)
            case.verify_intake(UserId(context.principal_id), verified_at)
            content: dict[str, Any] = {
                "source_mode": "manual_upload",
                "approval_reference": approval_reference.strip(),
                "comment": comment.strip(),
                "verified_by": str(context.principal_id),
                "verified_at": verified_at.isoformat(),
                "document_hashes": [document.content_hash for document in documents],
                "declaration": (
                    "Người xác minh xác nhận bản tải lên là PR đã được phê duyệt "
                    "trong môi trường mô phỏng."
                ),
            }
            await uow.artifacts.add(
                PreparationArtifact(
                    id=ArtifactId(self.id_generator.new_uuid()),
                    tenant_id=case.tenant_id,
                    workspace_id=case.workspace_id,
                    case_id=case.id,
                    artifact_type=ArtifactType.INTAKE_VERIFICATION,
                    schema_version="1.0",
                    artifact_version=1,
                    status=ArtifactStatus.APPROVED,
                    content=content,
                    created_by=UserId(context.principal_id),
                    content_hash=_content_hash(content),
                )
            )
            await uow.notifications.enqueue(
                IntakeNotificationJob(
                    id=self.id_generator.new_uuid(),
                    tenant_id=case.tenant_id,
                    workspace_id=case.workspace_id,
                    case_id=case.id,
                    event_type=IntakeNotificationType.APPROVED,
                    recipient_user_id=case.created_by,
                    due_at=verified_at,
                    idempotency_key=f"dw01:{case.id.value}:intake:approved:v{case.version}",
                    payload={
                        "title": case.title,
                        "approval_reference": approval_reference.strip(),
                        "comment": comment.strip(),
                    },
                )
            )
            await uow.cases.save(case)
            await uow.commit()

        # Human-in-command handoff: verification (approver) immediately kicks off
        # DW01, attributed to the case owner. A run failure must not fail the
        # verification itself — the owner can still press "Chạy DW01" manually.
        if self.run_case is not None:
            with contextlib.suppress(Exception):  # best-effort auto-start
                await self.run_case.handle_auto(case_id, context)


@dataclass
class RejectPreparationIntakeHandler:
    uow_factory: PreparationUnitOfWorkFactory
    authorization: ScopeAuthorizationService
    clock: UtcClock
    id_generator: IdGenerator
    # Optional so the handler stays constructible in tests and in deployments
    # where the support feature is not wired. Absent means: reject as before,
    # record nothing.
    rework_rules: ReworkSupportRules | None = None

    async def handle(
        self,
        case_id: uuid.UUID,
        *,
        comment: str,
        context: AccessContext,
        reason_code: str = "",
    ) -> None:
        await self.authorization.require(
            context=context,
            action="approvals.decide",
            resource_type="preparation_intake",
            resource_id=str(case_id),
        )
        reason = comment.strip()
        if not reason:
            raise DomainError("intake rejection requires a reason")
        async with self.uow_factory(TenantId(context.tenant_id)) as uow:
            case = await uow.cases.get(PreparationCaseId(case_id))
            if case is None:
                raise NotFoundError("preparation case not found")
            case.reject_intake(UserId(context.principal_id))
            now = self.clock.now().astimezone(UTC)
            if self.rework_rules is not None:
                # Same transaction as the state change on purpose: a case shown
                # as returned with no record would undercount in silence.
                await record_rework_event(
                    uow,
                    case=case,
                    decided_by=UserId(context.principal_id),
                    checkpoint=ReworkCheckpoint.INTAKE,
                    reason_code=reason_code,
                    reason_text=reason,
                    rules=self.rework_rules,
                    clock=self.clock,
                    id_generator=self.id_generator,
                )
            await uow.notifications.enqueue(
                IntakeNotificationJob(
                    id=self.id_generator.new_uuid(),
                    tenant_id=case.tenant_id,
                    workspace_id=case.workspace_id,
                    case_id=case.id,
                    event_type=IntakeNotificationType.REJECTED,
                    recipient_user_id=case.created_by,
                    due_at=now,
                    idempotency_key=f"dw01:{case.id.value}:intake:rejected:v{case.version}",
                    payload={"title": case.title, "comment": reason},
                )
            )
            await uow.cases.save(case)
            await uow.commit()


@dataclass(frozen=True)
class ClarificationAnswer:
    clarification_id: str
    question: str
    answer: str
    source_note: str


@dataclass
class AnswerPreparationClarificationsHandler:
    uow_factory: PreparationUnitOfWorkFactory
    authorization: ScopeAuthorizationService
    clock: UtcClock
    id_generator: IdGenerator

    async def handle(
        self,
        case_id: uuid.UUID,
        answers: tuple[ClarificationAnswer, ...],
        context: AccessContext,
    ) -> None:
        await self.authorization.require(
            context=context,
            action="tender.write",
            resource_type="preparation_clarification",
            resource_id=str(case_id),
        )
        if not answers or any(not item.answer.strip() for item in answers):
            raise DomainError("every clarification requires a non-empty answer")
        async with self.uow_factory(TenantId(context.tenant_id)) as uow:
            case = await uow.cases.get(PreparationCaseId(case_id))
            if case is None:
                raise NotFoundError("preparation case not found")
            if case.state is not CaseState.WAITING_CLARIFICATION:
                raise ConflictError(
                    "case is not waiting for clarification",
                    details={"state": case.state.value},
                )
            latest = await uow.artifacts.latest(case.id, ArtifactType.CLARIFICATION_RESPONSE)
            version = latest.artifact_version + 1 if latest is not None else 1
            answered_at = self.clock.now().astimezone(UTC)
            content: dict[str, Any] = {
                "answered_by": str(context.principal_id),
                "answered_at": answered_at.isoformat(),
                "items": [
                    {
                        "id": item.clarification_id,
                        "question": item.question.strip(),
                        "answer": item.answer.strip(),
                        "source_note": item.source_note.strip(),
                    }
                    for item in answers
                ],
            }
            await uow.artifacts.add(
                PreparationArtifact(
                    id=ArtifactId(self.id_generator.new_uuid()),
                    tenant_id=case.tenant_id,
                    workspace_id=case.workspace_id,
                    case_id=case.id,
                    artifact_type=ArtifactType.CLARIFICATION_RESPONSE,
                    schema_version="1.0",
                    artifact_version=version,
                    status=ArtifactStatus.SUBMITTED,
                    content=content,
                    created_by=UserId(context.principal_id),
                    content_hash=_content_hash(content),
                )
            )
            # Only leave WAITING_CLARIFICATION once every blocking question is
            # covered. Reopening on a PARTIAL answer stranded the case: the
            # chat clarification loop only runs while the case is waiting, and
            # nothing restarts the run until the last answer arrives — so the
            # case sat in intake_ready with an unanswered question and no way
            # back in.
            blocking_ids: set[str] = set()
            listing = await uow.artifacts.latest(case.id, ArtifactType.CLARIFICATION_LIST)
            if listing is not None:
                blocking_ids = {
                    str(item.get("id"))
                    for item in _dicts(listing.content.get("items"))
                    if item.get("blocking")
                }
            answered_ids = {item.clarification_id for item in answers}
            for artifact in await uow.artifacts.list_for_case(case.id):
                if artifact.artifact_type is not ArtifactType.CLARIFICATION_RESPONSE:
                    continue
                answered_ids.update(
                    str(item.get("id"))
                    for item in _dicts(artifact.content.get("items"))
                    if str(item.get("answer", "")).strip()
                )
            if blocking_ids <= answered_ids:
                case.reopen_after_clarification()
                await uow.cases.save(case)
            await uow.commit()


@dataclass(frozen=True)
class RecordPublicationCommand:
    filename: str
    content_type: str
    content: bytes
    channel: str
    recipient_summary: str
    published_at: str
    external_reference: str


@dataclass
class RecordPreparationPublicationHandler:
    uow_factory: PreparationUnitOfWorkFactory
    storage: DocumentStoragePort
    authorization: ScopeAuthorizationService
    clock: UtcClock
    id_generator: IdGenerator

    async def handle(
        self,
        case_id: uuid.UUID,
        command: RecordPublicationCommand,
        context: AccessContext,
    ) -> None:
        await self.authorization.require(
            context=context,
            action="tender.write",
            resource_type="preparation_publication",
            resource_id=str(case_id),
        )
        if not command.external_reference.strip():
            raise DomainError("publication external reference must not be blank")
        async with self.uow_factory(TenantId(context.tenant_id)) as uow:
            case = await uow.cases.get(PreparationCaseId(case_id))
            if case is None:
                raise NotFoundError("preparation case not found")
            if case.state is not CaseState.PACKAGE_OFFICIAL:
                raise ConflictError(
                    "only the official package can be recorded as published",
                    details={"state": case.state.value},
                )
            document = await _store_source_document(
                storage=self.storage,
                id_generator=self.id_generator,
                case=case,
                actor=UserId(context.principal_id),
                kind=DocumentKind.PUBLICATION_RECEIPT,
                title="Bằng chứng phát hành hồ sơ",
                filename=command.filename,
                content_type=command.content_type,
                content=command.content,
            )
            await uow.documents.add(document)
            recorded_at = self.clock.now().astimezone(UTC)
            artifact_content: dict[str, Any] = {
                "source_mode": "manual_evidence_upload",
                "channel": command.channel.strip(),
                "recipient_summary": command.recipient_summary.strip(),
                "published_at": command.published_at.strip(),
                "external_reference": command.external_reference.strip(),
                "receipt_document_id": str(document.id.value),
                "receipt_hash": document.content_hash,
                "recorded_by": str(context.principal_id),
                "recorded_at": recorded_at.isoformat(),
            }
            await _add_application_artifact(
                uow=uow,
                id_generator=self.id_generator,
                case=case,
                actor=UserId(context.principal_id),
                artifact_type=ArtifactType.PUBLICATION_RECORD,
                content=artifact_content,
                status=ArtifactStatus.OFFICIAL,
            )
            case.record_publication(await _bids_close_at(uow, case, recorded_at))
            await uow.cases.save(case)
            await uow.commit()


@dataclass
class AutoPublishPreparationHandler:
    """Publishes the official package by emailing the invited suppliers, then
    records the publication automatically (no manual evidence upload)."""

    uow_factory: PreparationUnitOfWorkFactory
    storage: DocumentStoragePort
    authorization: ScopeAuthorizationService
    clock: UtcClock
    id_generator: IdGenerator
    email_publisher: EmailPublisherPort
    recipient_email: str

    async def handle(self, case_id: uuid.UUID, context: AccessContext) -> dict[str, str]:
        await self.authorization.require(
            context=context,
            action="tender.write",
            resource_type="preparation_publication",
            resource_id=str(case_id),
        )
        async with self.uow_factory(TenantId(context.tenant_id)) as uow:
            case = await uow.cases.get(PreparationCaseId(case_id))
            if case is None:
                raise NotFoundError("preparation case not found")
            if case.state is not CaseState.PACKAGE_OFFICIAL:
                raise ConflictError(
                    "only the official package can be published",
                    details={"state": case.state.value},
                )
            package = await uow.artifacts.latest(case.id, ArtifactType.SOLICITATION_PACKAGE)
            shortlist_art = await uow.artifacts.latest(case.id, ArtifactType.SUPPLIER_SHORTLIST)
            raw_shortlist = shortlist_art.content.get("shortlist") if shortlist_art else None
            shortlist_items = raw_shortlist if isinstance(raw_shortlist, list) else []
            suppliers = [
                str(s.get("name", ""))
                for s in shortlist_items
                if isinstance(s, dict) and str(s.get("name", "")).strip()
            ]
            # The [DW01:<case-id>] tag survives "Re:" replies — the email
            # submission ingest (mailroom) uses it to route bids to the case.
            subject = (
                f"[MỜI CHÀO GIÁ][DW01:{case.id.value}] {case.title} — {case.source_pr_ref or ''}"
            ).strip()
            body = _build_rfq_email_body(case, package.content if package else {})

            # Send first — if email fails we do NOT record a publication.
            message_id = await self.email_publisher.send(
                subject=subject, body=body, to=self.recipient_email
            )

            recorded_at = self.clock.now().astimezone(UTC)
            evidence = (
                f"Đã gửi tự động qua email tới {self.recipient_email}\n"
                f"Message-ID: {message_id}\nThời điểm: {recorded_at.isoformat()}\n\n{body}"
            ).encode()
            document = await _store_source_document(
                storage=self.storage,
                id_generator=self.id_generator,
                case=case,
                actor=UserId(context.principal_id),
                kind=DocumentKind.PUBLICATION_RECEIPT,
                title="Bằng chứng phát hành (email tự động)",
                filename="publication_email.txt",
                content_type="text/plain; charset=utf-8",
                content=evidence,
            )
            await uow.documents.add(document)
            artifact_content: dict[str, Any] = {
                "source_mode": "auto_email",
                "channel": "Email công vụ (tự động)",
                "recipient_summary": (", ".join(suppliers) if suppliers else self.recipient_email),
                "published_at": recorded_at.isoformat(),
                "external_reference": message_id,
                "sent_to": self.recipient_email,
                "receipt_document_id": str(document.id.value),
                "receipt_hash": document.content_hash,
                "recorded_by": str(context.principal_id),
                "recorded_at": recorded_at.isoformat(),
            }
            await _add_application_artifact(
                uow=uow,
                id_generator=self.id_generator,
                case=case,
                actor=UserId(context.principal_id),
                artifact_type=ArtifactType.PUBLICATION_RECORD,
                content=artifact_content,
                status=ArtifactStatus.OFFICIAL,
            )
            case.record_publication(await _bids_close_at(uow, case, recorded_at))
            # P3 trace + next-step guidance: after publication the flow is
            # chat-driven (submissions/CP3/CP4) — without this card the owner
            # has no idea what unlocks the next checkpoint.
            await uow.notifications.enqueue(
                IntakeNotificationJob(
                    id=self.id_generator.new_uuid(),
                    tenant_id=case.tenant_id,
                    workspace_id=case.workspace_id,
                    case_id=case.id,
                    event_type=IntakeNotificationType.RUN_PROGRESS,
                    recipient_user_id=case.created_by,
                    due_at=recorded_at,
                    idempotency_key=f"dw01:{case.id.value}:progress:published",
                    payload={
                        "title": case.title,
                        "heading": "Đã phát hành hồ sơ mời thầu qua email",
                        "lines": [
                            (
                                "Đã gửi tới: "
                                + (", ".join(suppliers) if suppliers else self.recipient_email)
                                + "."
                            ),
                            "Nhà cung cấp sẽ nộp hồ sơ về bộ phận mua sắm — quản lý "
                            "ghi nhận và mở thầu, mình sẽ báo tiến độ tại đây.",
                            # This card goes to the REQUESTER, who cannot file
                            # an addendum — only propose one. Promising to file
                            # it described what happens for procurement, not
                            # for the person actually reading the sentence.
                            "Riêng bạn: cần sửa đổi/gia hạn thì nhắn nội dung, "
                            "mình chuyển đề nghị sang bộ phận mua sắm — họ lập "
                            "bản sửa đổi và trình duyệt.",
                        ],
                    },
                )
            )
            # Receipt desk for procurement (bước 8 — tiếp nhận HSDT thuộc bộ
            # phận mua sắm, KHÔNG phải người đề nghị): the approver records
            # each incoming bid with one click, then closes and opens bids.
            approver = await uow.notifications.find_recipient_for_role("approver")
            if approver is not None:
                # Slack requires UNIQUE action_ids within a block — suffix the
                # index; the handler dispatches on the prefix before ":".
                # No "Chốt sổ" button yet — it only appears (server-rendered)
                # once at least one bid has been recorded with its file.
                receipt_buttons: list[dict[str, str]] = [
                    {
                        "action_id": f"dw01_record_sub:{i}",
                        "label": f"{name} đã nộp",
                        "value": f"{case.id.value}|{name}",
                    }
                    for i, name in enumerate(suppliers[:4])
                ]
                await uow.notifications.enqueue(
                    IntakeNotificationJob(
                        id=self.id_generator.new_uuid(),
                        tenant_id=case.tenant_id,
                        workspace_id=case.workspace_id,
                        case_id=case.id,
                        event_type=IntakeNotificationType.RUN_PROGRESS,
                        recipient_user_id=approver,
                        due_at=recorded_at,
                        idempotency_key=f"dw01:{case.id.value}:progress:receipt_desk",
                        payload={
                            "title": case.title,
                            "heading": "Tiếp nhận hồ sơ dự thầu",
                            "lines": [
                                (f"RFQ đã phát hành tới {len(suppliers) or 1} nhà cung cấp."),
                                "Khi nhận hồ sơ dự thầu: bấm nút của nhà cung cấp "
                                "rồi thả FILE hồ sơ vào DM — mình lưu bản chính "
                                "thức và lập biên nhận.",
                                "Nút Chốt sổ & mở thầu sẽ hiện khi có ít nhất 1 "
                                "hồ sơ được ghi nhận.",
                            ],
                            "buttons": receipt_buttons,
                        },
                    )
                )
            await uow.cases.save(case)
            await uow.commit()
        return {"message_id": message_id, "sent_to": self.recipient_email}


async def _invited_supplier_names(uow: PreparationUnitOfWork, case: PreparationCase) -> str:
    """Who holds the invitation, read from the shortlist the package went to."""
    shortlist = await uow.artifacts.latest(case.id, ArtifactType.SUPPLIER_SHORTLIST)
    rows = shortlist.content.get("shortlist") if shortlist else None
    names = [
        str(row.get("name", "")).strip()
        for row in (rows if isinstance(rows, list) else [])
        if isinstance(row, dict) and str(row.get("name", "")).strip()
    ]
    return ", ".join(names)


def _build_addendum_email_body(case: PreparationCase, change: str, impact: str) -> str:
    """Sent to ONE supplier at a time — never name the others (see RFQ body)."""
    lines = [
        "Kính gửi Quý nhà cung cấp,",
        "",
        f"Bên mời thầu thông báo SỬA ĐỔI hồ sơ mời thầu gói: {case.title}.",
        "",
        "## Nội dung sửa đổi",
        change or "(không nêu)",
    ]
    if impact:
        lines += ["", "## Ảnh hưởng", impact]
    if case.bids_close_at is not None:
        lines += ["", f"## Hạn nộp hồ sơ dự thầu\n{case.bids_close_at:%d/%m/%Y %H:%M} (giờ VN)"]
    lines += [
        "",
        "Sửa đổi này là một phần không tách rời của hồ sơ mời thầu. "
        "Đề nghị Quý nhà cung cấp cập nhật hồ sơ dự thầu theo nội dung trên.",
        "",
        "Trân trọng,",
        "Bên mời thầu",
    ]
    return "\n".join(lines)


def _addendum_effect_lines(
    *,
    approve: bool,
    issued: dict[str, str],
    extend_days: int,
    closed_before: datetime | None,
    closes_at: datetime | None,
) -> list[str]:
    """What the decision actually did — never what it was supposed to do."""
    if not approve:
        return ["Addendum không có hiệu lực; HSMT giữ nguyên."]
    lines = []
    if issued.get("issued_to"):
        lines.append(f"Đã gửi sửa đổi tới: {issued['issued_to']}.")
    else:
        lines.append("⚠️ Chưa gửi được tới nhà cung cấp — chưa cấu hình kênh phát hành.")
    if extend_days > 0 and closes_at is not None and closes_at != closed_before:
        lines.append(f"Hạn nộp thầu lùi {extend_days} ngày → {closes_at:%d/%m/%Y %H:%M}.")
    elif extend_days > 0:
        lines.append(
            f"Gia hạn {extend_days} ngày đã duyệt, nhưng gói này chưa có mốc đóng sổ để dời."
        )
    lines.append("Tiếp tục tiếp nhận hồ sơ dự thầu.")
    return lines


async def _bids_close_at(
    uow: PreparationUnitOfWork, case: PreparationCase, published_at: datetime
) -> datetime | None:
    """Publication plus the solicitation window the approach step derived.

    That window was already checked against the retrieved legal minimum at the
    CP2 gate, so it is read here rather than recomputed. An older case with no
    window recorded leaves the moment unset and keeps the previous behaviour.

    Shared because it was not: the manual-evidence path computed it and the
    auto-email path — the one the demo actually runs — called
    ``record_publication()`` with no argument at all, so every automatically
    published case had no closing moment and the register never closed on time.

    The window's owner is ``legal_constraints.applied_window_days`` on the
    approach artifact, where the node records the number it actually applied
    after reconciling the method default against the legal minimum it read out
    of the retrieved passages. Both callers used to look for a top-level
    ``solicitation_window_days``, which lives in the graph's state and is never
    written to the artifact — so the lookup silently found nothing every time.
    """
    approach = await uow.artifacts.latest(case.id, ArtifactType.PROCUREMENT_APPROACH)
    if approach is None:
        return None
    constraints = approach.content.get("legal_constraints")
    raw_window = constraints.get("applied_window_days") if isinstance(constraints, dict) else None
    if not isinstance(raw_window, int | str):
        return None
    with contextlib.suppress(TypeError, ValueError):
        days = int(raw_window)
        if days > 0:
            return published_at + timedelta(days=days)
    return None


def _build_rfq_email_body(case: PreparationCase, package: dict[str, Any]) -> str:
    # NOTE: this body is sent to ONE supplier at a time — never list the other
    # invited suppliers here (bidders must not learn who they compete against).
    scope = str(package.get("scope", "")).strip()
    reqs = [str(r) for r in package.get("requirements", [])]
    lines = [
        "Kính gửi Quý nhà cung cấp,",
        "",
        f"Công ty trân trọng mời Quý đơn vị tham gia chào giá cho gói: {case.title}.",
        f"Mã tham chiếu: {case.source_pr_ref or '—'}.",
        "",
        "PHẠM VI CUNG CẤP:",
        scope or "(theo hồ sơ mời thầu đính kèm)",
        "",
        "YÊU CẦU KỸ THUẬT CHÍNH:",
    ]
    lines += [f"- {r}" for r in reqs] or ["- (theo hồ sơ mời thầu đính kèm)"]
    lines += [
        "",
        "Thời hạn nộp hồ sơ: trong vòng 14 ngày kể từ ngày phát hành.",
        "Đề nghị Quý đơn vị gửi báo giá theo biểu mẫu đính kèm.",
        "",
        "Trân trọng,",
        "Phòng Mua sắm.",
    ]
    return "\n".join(lines)


@dataclass(frozen=True)
class ProposeAddendumCommand:
    change_summary: str
    impact_summary: str
    proposer_name: str
    # Days added to the bid-submission window, when the person named a number.
    extend_bids_by_days: int = 0


@dataclass
class ProposePreparationAddendumHandler:
    """Requester-side addendum PROPOSAL (role fix, see ADR-020 discussion).

    The requester never files CP3 paperwork — this only notifies the
    procurement side with a decision card: [Lập addendum & trình CP3] or
    dismiss. Actual drafting/submission happens with the procurement user's
    identity via ``SubmitPreparationAddendumHandler``, which enforces that
    identity itself rather than trusting this routing.

    Who receives the card is read from the role assignment in the database,
    not named here.
    """

    uow_factory: PreparationUnitOfWorkFactory
    authorization: ScopeAuthorizationService
    clock: UtcClock
    id_generator: IdGenerator

    async def handle(
        self,
        case_id: uuid.UUID,
        command: ProposeAddendumCommand,
        context: AccessContext,
    ) -> None:
        await self.authorization.require(
            context=context,
            action="tender.write",
            resource_type="preparation_addendum_proposal",
            resource_id=str(case_id),
        )
        change = command.change_summary.strip()
        async with self.uow_factory(TenantId(context.tenant_id)) as uow:
            case = await uow.cases.get(PreparationCaseId(case_id))
            if case is None:
                raise NotFoundError("preparation case not found")
            if case.state is not CaseState.PUBLISHED:
                raise ConflictError(
                    "addendum can only be proposed while the package is published",
                    details={"state": case.state.value},
                )
            recipient = await uow.notifications.find_recipient_for_role("approver")
            if recipient is None:
                raise NotFoundError("no procurement recipient configured for addendum proposals")
            button_value = json.dumps(
                {
                    "case_id": str(case.id.value),
                    "change": change[:600],
                    "impact": command.impact_summary.strip()[:400],
                    "proposer": command.proposer_name[:80],
                    "extend_days": command.extend_bids_by_days,
                },
                ensure_ascii=False,
            )
            await uow.notifications.enqueue(
                IntakeNotificationJob(
                    id=self.id_generator.new_uuid(),
                    tenant_id=case.tenant_id,
                    workspace_id=case.workspace_id,
                    case_id=case.id,
                    event_type=IntakeNotificationType.ADDENDUM_PROPOSED,
                    recipient_user_id=recipient,
                    due_at=self.clock.now(),
                    idempotency_key=(
                        f"dw01:{case.id.value}:addm-proposal:"
                        f"{hashlib.sha256(change.encode()).hexdigest()[:12]}"
                    ),
                    payload={
                        "title": case.title,
                        "heading": "📝 Đề nghị sửa đổi HSMT (từ người yêu cầu)",
                        "case_id": str(case.id.value),
                        "lines": [
                            f"Người đề nghị: {command.proposer_name}",
                            f"Nội dung: {change[:300]}",
                            (
                                "Ảnh hưởng (tự khai): "
                                + (command.impact_summary.strip()[:200] or "chưa nêu")
                            ),
                            "Bạn là bên mời thầu — quyết định có lập addendum hay không.",
                        ],
                        "buttons": [
                            {
                                "action_id": "dw01_addendum_submit",
                                "label": "📝 Lập addendum & trình CP3",
                                "value": button_value,
                                "style": "primary",
                            },
                            {
                                "action_id": "dw01_addendum_dismiss",
                                "label": "Bỏ qua đề nghị",
                                "value": str(case.id.value),
                            },
                        ],
                    },
                )
            )
            await uow.commit()


@dataclass(frozen=True)
class SubmitAddendumCommand:
    filename: str
    content_type: str
    content: bytes
    change_summary: str
    impact_summary: str
    # Carried onto the draft so CP3 can apply it without re-reading prose.
    extend_bids_by_days: int = 0


@dataclass
class SubmitPreparationAddendumHandler:
    """Files the addendum as the procuring entity, and only for them.

    An addendum is a formal document sent to everyone who was invited, so the
    party that issued the invitation is the party that may change it. The chat
    router already splits on this — a requester's "gia hạn thêm 10 ngày" turns
    into a proposal, procurement's turns into a filing — but that is routing,
    and routing is not authorization. Requiring only ``tender.write`` here let
    the requester reach the same mutation through the decision-card action or
    the API, because ``tender.write`` is what lets them open a case at all.
    The scope is the one the router reads, so both resolve from one source.
    """

    uow_factory: PreparationUnitOfWorkFactory
    storage: DocumentStoragePort
    authorization: ScopeAuthorizationService
    clock: UtcClock
    id_generator: IdGenerator

    async def handle(
        self,
        case_id: uuid.UUID,
        command: SubmitAddendumCommand,
        context: AccessContext,
    ) -> None:
        await self.authorization.require(
            context=context,
            action="approvals.decide",
            resource_type="preparation_addendum",
            resource_id=str(case_id),
        )
        async with self.uow_factory(TenantId(context.tenant_id)) as uow:
            case = await uow.cases.get(PreparationCaseId(case_id))
            if case is None:
                raise NotFoundError("preparation case not found")
            if case.state is not CaseState.PUBLISHED:
                raise ConflictError(
                    "addendum can only be submitted before receiving bids",
                    details={"state": case.state.value},
                )
            document = await _store_source_document(
                storage=self.storage,
                id_generator=self.id_generator,
                case=case,
                actor=UserId(context.principal_id),
                kind=DocumentKind.ADDENDUM,
                title="Dự thảo addendum",
                filename=command.filename,
                content_type=command.content_type,
                content=command.content,
            )
            await uow.documents.add(document)
            content: dict[str, Any] = {
                "document_id": str(document.id.value),
                "document_hash": document.content_hash,
                "change_summary": command.change_summary.strip(),
                "impact_summary": command.impact_summary.strip(),
                # Read back by CP3 to move the closing moment. Stored on the
                # draft, not re-parsed from prose, so what the approver signs
                # and what the register does are the same number.
                "extend_bids_by_days": command.extend_bids_by_days,
                "submitted_by": str(context.principal_id),
                "submitted_at": self.clock.now().astimezone(UTC).isoformat(),
            }
            await _add_application_artifact(
                uow=uow,
                id_generator=self.id_generator,
                case=case,
                actor=UserId(context.principal_id),
                artifact_type=ArtifactType.ADDENDUM_DRAFT,
                content=content,
                status=ArtifactStatus.SUBMITTED,
            )
            case.submit_addendum()
            # P4: decision card for the approver — CP3 is decided in Slack.
            approver = await uow.notifications.find_recipient_for_role("approver")
            if approver is not None:
                await uow.notifications.enqueue(
                    IntakeNotificationJob(
                        id=self.id_generator.new_uuid(),
                        tenant_id=case.tenant_id,
                        workspace_id=case.workspace_id,
                        case_id=case.id,
                        event_type=IntakeNotificationType.CP_APPROVAL_REQUESTED,
                        recipient_user_id=approver,
                        due_at=self.clock.now(),
                        idempotency_key=(
                            f"dw01:{case.id.value}:cpcard:CP3:{document.content_hash[:12]}"
                        ),
                        payload={
                            "title": case.title,
                            "checkpoint": "CP3",
                            "case_id": str(case.id.value),
                            "lines": [
                                f"Nội dung sửa đổi: {command.change_summary.strip()[:200]}",
                                (
                                    "Ảnh hưởng: "
                                    + (command.impact_summary.strip()[:200] or "chưa đánh giá")
                                ),
                                "Văn bản addendum do hệ thống soạn từ trao đổi Slack.",
                            ],
                        },
                    )
                )
            await uow.cases.save(case)
            await uow.commit()


@dataclass
class DecidePreparationCp3Handler:
    """Decides CP3 and, on approval, actually issues the addendum.

    An addendum only means anything once every supplier holding the invitation
    has it — a change some bidders know about and others do not is exactly the
    unfairness the instrument exists to prevent. Approval used to write an
    ``addendum_decision`` artifact and stop there, so the document was an
    internal record of a decision rather than an amendment to the solicitation.

    Dispatch mirrors publication: same email port, same publication record, so
    "who was told, when, with what message id" is answered the same way for the
    original package and for every change to it.
    """

    uow_factory: PreparationUnitOfWorkFactory
    authorization: ScopeAuthorizationService
    clock: UtcClock
    id_generator: IdGenerator
    storage: DocumentStoragePort | None = None
    email_publisher: EmailPublisherPort | None = None
    recipient_email: str = ""

    async def handle(
        self,
        case_id: uuid.UUID,
        *,
        approve: bool,
        approval_reference: str,
        comment: str,
        context: AccessContext,
    ) -> None:
        await self.authorization.require(
            context=context,
            action="approvals.decide",
            resource_type="preparation_cp3",
            resource_id=str(case_id),
        )
        if not approval_reference.strip():
            raise DomainError("CP3 approval reference must not be blank")
        async with self.uow_factory(TenantId(context.tenant_id)) as uow:
            case = await uow.cases.get(PreparationCaseId(case_id))
            if case is None:
                raise NotFoundError("preparation case not found")
            if case.created_by.value == context.principal_id:
                raise ConflictError("case creator cannot decide CP3 for their own case")
            if case.state is not CaseState.CP3_PENDING:
                raise ConflictError(
                    "case is not waiting for CP3",
                    details={"state": case.state.value},
                )
            draft = await uow.artifacts.latest(case.id, ArtifactType.ADDENDUM_DRAFT)
            if draft is None:
                raise DomainError("CP3 has no addendum draft")
            raw_extend = draft.content.get("extend_bids_by_days")
            extend_days = raw_extend if isinstance(raw_extend, int) and raw_extend > 0 else 0
            issued: dict[str, str] = {}
            if approve:
                # Send BEFORE recording, exactly as publication does: a record
                # of an issue that never left the building is worse than none.
                issued = await self._issue_to_suppliers(
                    uow=uow, case=case, draft=draft, context=context
                )
            decision_content: dict[str, Any] = {
                "decision": "approved" if approve else "rejected",
                "approval_reference": approval_reference.strip(),
                "comment": comment.strip(),
                "addendum_artifact_id": str(draft.id.value),
                "addendum_hash": draft.content_hash,
                "extend_bids_by_days": extend_days if approve else 0,
                "decided_by": str(context.principal_id),
                "decided_at": self.clock.now().astimezone(UTC).isoformat(),
                **issued,
            }
            await _add_application_artifact(
                uow=uow,
                id_generator=self.id_generator,
                case=case,
                actor=UserId(context.principal_id),
                artifact_type=ArtifactType.ADDENDUM_DECISION,
                content=decision_content,
                status=ArtifactStatus.APPROVED if approve else ArtifactStatus.DRAFT,
            )
            closed_before = case.bids_close_at
            case.resolve_cp3(extend_bids_by_days=extend_days if approve else 0)
            # P3 trace: tell the owner what was decided.
            await uow.notifications.enqueue(
                IntakeNotificationJob(
                    id=self.id_generator.new_uuid(),
                    tenant_id=case.tenant_id,
                    workspace_id=case.workspace_id,
                    case_id=case.id,
                    event_type=IntakeNotificationType.RUN_PROGRESS,
                    recipient_user_id=case.created_by,
                    due_at=self.clock.now(),
                    idempotency_key=(
                        f"dw01:{case.id.value}:progress:cp3_decision:{draft.content_hash[:12]}"
                    ),
                    payload={
                        "title": case.title,
                        "heading": (
                            "✅ CP3 — Sửa đổi ĐÃ ĐƯỢC DUYỆT"
                            if approve
                            else "⛔ CP3 — Sửa đổi bị TỪ CHỐI"
                        ),
                        "lines": [
                            f"Tham chiếu phê duyệt: {approval_reference.strip()}.",
                            (comment.strip() or "Không có nhận xét."),
                            *_addendum_effect_lines(
                                approve=approve,
                                issued=issued,
                                extend_days=extend_days,
                                closed_before=closed_before,
                                closes_at=case.bids_close_at,
                            ),
                        ],
                    },
                )
            )
            await uow.cases.save(case)
            await uow.commit()

    async def _issue_to_suppliers(
        self,
        *,
        uow: PreparationUnitOfWork,
        case: PreparationCase,
        draft: PreparationArtifact,
        context: AccessContext,
    ) -> dict[str, str]:
        """Email the approved addendum to everyone holding the invitation.

        Returns the delivery facts to be stamped onto the decision. An
        unconfigured publisher returns nothing rather than raising: a
        deployment without email must still be able to decide CP3, and the
        empty record is what tells the reader nobody was sent to.
        """
        if self.email_publisher is None or self.storage is None or not self.recipient_email:
            return {}
        change = str(draft.content.get("change_summary", "")).strip()
        impact = str(draft.content.get("impact_summary", "")).strip()
        subject = f"[SỬA ĐỔI HSMT][DW01:{case.id.value}] {case.title}"
        body = _build_addendum_email_body(case, change, impact)
        message_id = await self.email_publisher.send(
            subject=subject, body=body, to=self.recipient_email
        )
        sent_at = self.clock.now().astimezone(UTC)
        document = await _store_source_document(
            storage=self.storage,
            id_generator=self.id_generator,
            case=case,
            actor=UserId(context.principal_id),
            kind=DocumentKind.PUBLICATION_RECEIPT,
            title="Bằng chứng phát hành sửa đổi (email tự động)",
            filename="addendum_email.txt",
            content_type="text/plain; charset=utf-8",
            content=(
                f"Đã gửi tự động qua email tới {self.recipient_email}\n"
                f"Message-ID: {message_id}\nThời điểm: {sent_at.isoformat()}\n\n{body}"
            ).encode(),
        )
        await uow.documents.add(document)
        await _add_application_artifact(
            uow=uow,
            id_generator=self.id_generator,
            case=case,
            actor=UserId(context.principal_id),
            artifact_type=ArtifactType.PUBLICATION_RECORD,
            content={
                "source_mode": "addendum_email",
                "channel": "Email công vụ (tự động)",
                "recipient_summary": await _invited_supplier_names(uow, case)
                or self.recipient_email,
                "published_at": sent_at.isoformat(),
                "external_reference": message_id,
                "sent_to": self.recipient_email,
                "receipt_document_id": str(document.id.value),
                "receipt_hash": document.content_hash,
                "addendum_artifact_id": str(draft.id.value),
                "recorded_by": str(context.principal_id),
                "recorded_at": sent_at.isoformat(),
            },
            status=ArtifactStatus.OFFICIAL,
        )
        return {
            "issued_message_id": message_id,
            "issued_to": await _invited_supplier_names(uow, case) or self.recipient_email,
            "issued_at": sent_at.isoformat(),
        }


@dataclass(frozen=True)
class RecordSubmissionCommand:
    filename: str
    content_type: str
    content: bytes
    supplier_name: str
    received_at: str
    receipt_status: str
    external_reference: str


@dataclass
class RecordPreparationSubmissionHandler:
    uow_factory: PreparationUnitOfWorkFactory
    storage: DocumentStoragePort
    authorization: ScopeAuthorizationService
    clock: UtcClock
    id_generator: IdGenerator
    rules: ProcurementRules

    async def handle(
        self,
        case_id: uuid.UUID,
        command: RecordSubmissionCommand,
        context: AccessContext,
    ) -> None:
        await self.authorization.require(
            context=context,
            action="tender.write",
            resource_type="supplier_submission",
            resource_id=str(case_id),
        )
        if command.receipt_status not in {"on_time", "late", "replacement"}:
            raise DomainError("invalid supplier submission receipt status")
        async with self.uow_factory(TenantId(context.tenant_id)) as uow:
            case = await uow.cases.get(PreparationCaseId(case_id))
            if case is None:
                raise NotFoundError("preparation case not found")
            if case.state not in {CaseState.PUBLISHED, CaseState.RECEIVING_BIDS}:
                raise ConflictError(
                    "case is not accepting supplier submissions",
                    details={"state": case.state.value},
                )
            document = await _store_source_document(
                storage=self.storage,
                id_generator=self.id_generator,
                case=case,
                actor=UserId(context.principal_id),
                kind=DocumentKind.SUPPLIER_SUBMISSION,
                title=f"Hồ sơ dự thầu — {command.supplier_name.strip()}",
                filename=command.filename,
                content_type=command.content_type,
                content=command.content,
            )
            await uow.documents.add(document)
            latest = await uow.artifacts.latest(case.id, ArtifactType.SUBMISSION_REGISTER)
            prior_items = latest.content.get("items", []) if latest is not None else []
            items = (
                [dict(item) for item in prior_items if isinstance(item, dict)]
                if isinstance(prior_items, list)
                else []
            )
            items.append(
                {
                    "submission_id": str(document.id.value),
                    "supplier_name": command.supplier_name.strip(),
                    "filename": document.filename,
                    "content_hash": document.content_hash,
                    "received_at": command.received_at.strip(),
                    "receipt_status": command.receipt_status,
                    "external_reference": command.external_reference.strip(),
                    "recorded_by": str(context.principal_id),
                    "recorded_at": self.clock.now().astimezone(UTC).isoformat(),
                }
            )
            await _add_application_artifact(
                uow=uow,
                id_generator=self.id_generator,
                case=case,
                actor=UserId(context.principal_id),
                artifact_type=ArtifactType.SUBMISSION_REGISTER,
                content={"source_mode": "manual_evidence_upload", "items": items},
                status=ArtifactStatus.SUBMITTED,
            )
            case.record_submission()
            # A bid landing used to tell nobody on our side — only the supplier
            # got an acknowledgement. It goes to whoever will run the opening;
            # the requester has nothing to do with a bid arriving and gets told
            # at the stages that actually concern them.
            opener = await uow.notifications.find_recipient_for_role(
                self.rules.approver_role_for(case.estimated_value_minor, "CP4")
            )
            if opener is not None:
                await uow.notifications.enqueue(
                    IntakeNotificationJob(
                        id=self.id_generator.new_uuid(),
                        tenant_id=case.tenant_id,
                        workspace_id=case.workspace_id,
                        case_id=case.id,
                        event_type=IntakeNotificationType.RUN_PROGRESS,
                        recipient_user_id=opener,
                        due_at=self.clock.now().astimezone(UTC),
                        idempotency_key=(
                            f"dw01:{case.id.value}:progress:bid:{document.content_hash[:12]}"
                        ),
                        payload={
                            "title": case.title,
                            "heading": (
                                f"Đã nhận hồ sơ dự thầu từ {command.supplier_name.strip()}"
                            ),
                            "lines": [
                                f"Sổ tiếp nhận hiện có {len(items)} hồ sơ.",
                                f"Tệp: {document.filename} · niêm phong bằng mã băm nội dung.",
                                "Biên nhận đã lập; nhà cung cấp đã được xác nhận qua email.",
                            ],
                        },
                    )
                )
            await uow.cases.save(case)
            await uow.commit()


@dataclass
class RequestCp4Handler:
    """Owner (via chat) asks to close the register and open bids: notify the
    approver with a CP4 confirmation card. No state change — CP4 itself is
    confirmed by the approver (SoD)."""

    uow_factory: PreparationUnitOfWorkFactory
    authorization: ScopeAuthorizationService
    clock: UtcClock
    id_generator: IdGenerator
    rules: ProcurementRules

    async def handle(self, case_id: uuid.UUID, context: AccessContext) -> int:
        await self.authorization.require(
            context=context,
            action="tender.write",
            resource_type="preparation_cp4",
            resource_id=str(case_id),
        )
        async with self.uow_factory(TenantId(context.tenant_id)) as uow:
            case = await uow.cases.get(PreparationCaseId(case_id))
            if case is None:
                raise NotFoundError("preparation case not found")
            if case.state is not CaseState.RECEIVING_BIDS:
                raise ConflictError(
                    "case is not receiving bids", details={"state": case.state.value}
                )
            documents = await uow.documents.list_for_case(case.id)
            submissions = [d for d in documents if d.kind is DocumentKind.SUPPLIER_SUBMISSION]
            if not submissions:
                raise DomainError("chưa có hồ sơ dự thầu nào — không thể mở thầu")
            approver = await uow.notifications.find_recipient_for_role(
                self.rules.approver_role_for(case.estimated_value_minor, "CP4")
            )
            if approver is not None:
                await uow.notifications.enqueue(
                    IntakeNotificationJob(
                        id=self.id_generator.new_uuid(),
                        tenant_id=case.tenant_id,
                        workspace_id=case.workspace_id,
                        case_id=case.id,
                        event_type=IntakeNotificationType.CP_APPROVAL_REQUESTED,
                        recipient_user_id=approver,
                        due_at=self.clock.now(),
                        idempotency_key=(f"dw01:{case.id.value}:cpcard:CP4:n{len(submissions)}"),
                        payload={
                            "title": case.title,
                            "checkpoint": "CP4",
                            "case_id": str(case.id.value),
                            "lines": [
                                f"Sổ tiếp nhận: {len(submissions)} hồ sơ dự thầu.",
                                "Người tạo đề nghị chốt sổ và mở thầu.",
                                "Xác nhận sẽ tự lập biên bản mở thầu và bàn giao "
                                "gói đánh giá cho DW02.",
                            ],
                        },
                    )
                )
            await uow.commit()
            return len(submissions)


@dataclass(frozen=True)
class CompleteCp4Command:
    filename: str
    content_type: str
    content: bytes
    opening_at: str
    witnesses: tuple[str, ...]
    approval_reference: str
    comment: str


@dataclass
class CompletePreparationCp4Handler:
    uow_factory: PreparationUnitOfWorkFactory
    storage: DocumentStoragePort
    authorization: ScopeAuthorizationService
    clock: UtcClock
    id_generator: IdGenerator

    async def handle(
        self,
        case_id: uuid.UUID,
        command: CompleteCp4Command,
        context: AccessContext,
    ) -> None:
        await self.authorization.require(
            context=context,
            action="approvals.decide",
            resource_type="preparation_cp4",
            resource_id=str(case_id),
        )
        if not command.approval_reference.strip() or not command.witnesses:
            raise DomainError("CP4 requires approval reference and at least one witness")
        async with self.uow_factory(TenantId(context.tenant_id)) as uow:
            case = await uow.cases.get(PreparationCaseId(case_id))
            if case is None:
                raise NotFoundError("preparation case not found")
            if case.created_by.value == context.principal_id:
                raise ConflictError("case creator cannot confirm CP4 for their own case")
            if case.state is not CaseState.RECEIVING_BIDS:
                raise ConflictError(
                    "case is not ready for CP4",
                    details={"state": case.state.value},
                )
            documents = await uow.documents.list_for_case(case.id)
            submissions = [
                item for item in documents if item.kind is DocumentKind.SUPPLIER_SUBMISSION
            ]
            if not submissions:
                raise DomainError("CP4 requires at least one supplier submission")
            minutes = await _store_source_document(
                storage=self.storage,
                id_generator=self.id_generator,
                case=case,
                actor=UserId(context.principal_id),
                kind=DocumentKind.BID_OPENING_MINUTES,
                title="Biên bản mở thầu",
                filename=command.filename,
                content_type=command.content_type,
                content=command.content,
            )
            await uow.documents.add(minutes)
            completed_at = self.clock.now().astimezone(UTC)
            opening_content: dict[str, Any] = {
                "opening_at": command.opening_at.strip(),
                "witnesses": list(command.witnesses),
                "approval_reference": command.approval_reference.strip(),
                "comment": command.comment.strip(),
                "minutes_document_id": str(minutes.id.value),
                "minutes_hash": minutes.content_hash,
                "confirmed_by": str(context.principal_id),
                "confirmed_at": completed_at.isoformat(),
            }
            await _add_application_artifact(
                uow=uow,
                id_generator=self.id_generator,
                case=case,
                actor=UserId(context.principal_id),
                artifact_type=ArtifactType.BID_OPENING_RECORD,
                content=opening_content,
                status=ArtifactStatus.APPROVED,
            )
            all_artifacts = await uow.artifacts.list_for_case(case.id)
            handoff_content: dict[str, Any] = {
                "case_id": str(case.id.value),
                "source_mode": "manual_evidence_upload",
                "official_package_artifact_id": (
                    str(case.current_official_artifact_id)
                    if case.current_official_artifact_id is not None
                    else None
                ),
                "submission_count": len(submissions),
                "submission_document_ids": [str(item.id.value) for item in submissions],
                "artifact_index": [
                    {
                        "type": item.artifact_type.value,
                        "version": item.artifact_version,
                        "hash": item.content_hash,
                    }
                    for item in all_artifacts
                ],
                "cp4_reference": command.approval_reference.strip(),
                "handoff_ready_at": completed_at.isoformat(),
            }
            handoff_bytes = json.dumps(handoff_content, ensure_ascii=False, indent=2).encode(
                "utf-8"
            )
            handoff_ref = await self.storage.put_object(
                (
                    f"{context.tenant_id}/{context.workspace_id}/exports/preparation/"
                    f"{case.id.value}/evaluation-handoff.json"
                ),
                handoff_bytes,
                "application/json",
            )
            handoff_content["handoff_ref"] = handoff_ref
            await _add_application_artifact(
                uow=uow,
                id_generator=self.id_generator,
                case=case,
                actor=UserId(context.principal_id),
                artifact_type=ArtifactType.EVALUATION_HANDOFF,
                content=handoff_content,
                status=ArtifactStatus.OFFICIAL,
            )
            case.complete_cp4_handoff()
            # P3 trace: closing card for the owner.
            await uow.notifications.enqueue(
                IntakeNotificationJob(
                    id=self.id_generator.new_uuid(),
                    tenant_id=case.tenant_id,
                    workspace_id=case.workspace_id,
                    case_id=case.id,
                    event_type=IntakeNotificationType.RUN_PROGRESS,
                    recipient_user_id=case.created_by,
                    due_at=self.clock.now(),
                    idempotency_key=f"dw01:{case.id.value}:progress:cp4_done",
                    payload={
                        "title": case.title,
                        "heading": "Đã mở thầu — hồ sơ niêm phong, chuyển sang bước đánh giá",
                        "lines": [
                            f"{len(submissions)} hồ sơ dự thầu đã mở; biên bản mở thầu "
                            "được hệ thống lập và lưu vào hồ sơ.",
                            "Gói bàn giao đánh giá (evaluation handoff) đã niêm phong.",
                            # The requester must not read "xong" as "đã mua": nothing is
                            # bought yet — no supplier chosen, no contract, no delivery.
                            "Lưu ý: đây mới là hết khâu chuẩn bị và tiếp nhận thầu — "
                            "chưa chọn được nhà cung cấp và chưa có hợp đồng.",
                            "Tiếp theo: đánh giá hồ sơ dự thầu, trình duyệt kết quả lựa "
                            "chọn nhà thầu, rồi mới thương thảo và ký hợp đồng.",
                        ],
                    },
                )
            )
            await uow.cases.save(case)
            await uow.commit()


@dataclass
class GetPreparationCaseHandler:
    uow_factory: PreparationUnitOfWorkFactory
    authorization: ScopeAuthorizationService
    storage: DocumentStoragePort | None = None
    # Only inline small text uploads (source PRs are a couple of KiB).
    max_inline_text_bytes: int = 256 * 1024

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
            documents = await uow.documents.list_for_case(case.id)
            notifications = await uow.notifications.list_for_case(case.id)
        document_texts = await self._inline_texts(documents)
        return PreparationCaseView.from_domain(
            case, artifacts, documents, notifications, document_texts=document_texts
        )

    async def _inline_texts(self, documents: list[PreparationDocument]) -> dict[uuid.UUID, str]:
        if self.storage is None:
            return {}
        texts: dict[uuid.UUID, str] = {}
        for doc in documents:
            is_text = doc.content_type.startswith("text/") or doc.filename.lower().endswith(
                (".txt", ".md", ".markdown", ".csv")
            )
            if not is_text or doc.size_bytes > self.max_inline_text_bytes:
                continue
            try:
                raw = await self.storage.get_object(doc.storage_key)
                texts[doc.id.value] = raw.decode("utf-8", errors="replace")
            except Exception:  # preview is best-effort, never fails the case load
                continue
        return texts


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
    rework_guard: ReworkGuard | None = None

    async def handle(
        self, case_id: uuid.UUID, context: AccessContext, *, channel: str = "web"
    ) -> uuid.UUID:
        # One handler serves the web button and a chat reply, so the caller has
        # to say which — this used to file every run as a web run.
        await self.authorization.require(
            context=context,
            action="tender.write",
            resource_type="preparation_case",
            resource_id=str(case_id),
        )
        # Gated because a run is what puts a case in front of an approver.
        # Editing and saving stay open — see ReworkGuard's docstring.
        if self.rework_guard is not None:
            await self.rework_guard.require_not_blocked(context)
        return await self._start(case_id, context, on_behalf_of_owner=False, channel=channel)

    async def handle_auto(self, case_id: uuid.UUID, context: AccessContext) -> uuid.UUID:
        """Auto-run triggered by a verified intake. The approver need not hold
        ``tender.write``; the run is attributed to the case owner instead."""
        return await self._start(case_id, context, on_behalf_of_owner=True, channel="auto_intake")

    async def _start(
        self, case_id: uuid.UUID, context: AccessContext, *, on_behalf_of_owner: bool, channel: str
    ) -> uuid.UUID:
        await self.entitlement.require_feature(context, TENDER_FEATURE)

        run_id = self.id_generator.new_uuid()
        async with self.uow_factory(TenantId(context.tenant_id)) as uow:
            case = await uow.cases.get(PreparationCaseId(case_id))
            if case is None:
                raise NotFoundError("preparation case not found", details={"case_id": str(case_id)})
            actor_id = str(case.created_by.value) if on_behalf_of_owner else context.principal_id
            case.start_run(run_id)
            # P3 activity trace: first progress card for the owner's Slack DM.
            await uow.notifications.enqueue(
                IntakeNotificationJob(
                    id=self.id_generator.new_uuid(),
                    tenant_id=case.tenant_id,
                    workspace_id=case.workspace_id,
                    case_id=case.id,
                    event_type=IntakeNotificationType.RUN_PROGRESS,
                    recipient_user_id=case.created_by,
                    due_at=datetime.now(tz=UTC),
                    idempotency_key=(
                        f"dw01:{case.id.value}:progress:run_started:{run_id.hex[:12]}"
                    ),
                    payload={
                        "title": case.title,
                        "heading": "Bắt đầu xử lý hồ sơ",
                        "lines": [
                            "Trình tự: đọc yêu cầu → đối chiếu quy định → "
                            "lập phương án → trình duyệt CP1 → soạn HSMT → CP2.",
                            "Xong bước nào mình nhắn bước đó tại đây.",
                        ],
                    },
                )
            )
            await uow.cases.save(case)
            await uow.commit()

        run_context = RunContext(
            run_id=run_id,
            tenant_id=context.tenant_id,
            workspace_id=context.workspace_id,
            actor_id=actor_id,
            worker_id=self.worker_id,
            worker_version=self.worker_version,
            channel=channel,
            plan_id=context.plan_id,
            roles=context.roles,
            scopes=context.scopes,
            trace_id=f"run-{run_id.hex[:12]}",
        )
        await self.workflow_runner.start(
            run_context=run_context, input_payload={"case_id": str(case_id)}
        )
        return run_id


def _dicts(raw: object) -> list[dict[str, Any]]:
    """Artifact content is free-form JSON; keep only the dict items."""
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _content_hash(content: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


async def _store_source_document(
    *,
    storage: DocumentStoragePort,
    id_generator: IdGenerator,
    case: PreparationCase,
    actor: UserId,
    kind: DocumentKind,
    title: str,
    filename: str,
    content_type: str,
    content: bytes,
) -> PreparationDocument:
    if not content:
        raise DomainError("uploaded evidence file must not be empty")
    document_id = PreparationDocumentId(id_generator.new_uuid())
    storage_key = (
        f"{case.tenant_id.value}/{case.workspace_id.value}/preparation/{case.id.value}/"
        f"sources/{document_id.value}/{filename}"
    )
    await storage.put_object(storage_key, content, content_type)
    return PreparationDocument(
        id=document_id,
        tenant_id=case.tenant_id,
        workspace_id=case.workspace_id,
        case_id=case.id,
        kind=kind,
        title=title,
        filename=filename,
        content_type=content_type,
        size_bytes=len(content),
        storage_key=storage_key,
        content_hash=hashlib.sha256(content).hexdigest(),
        uploaded_by=actor,
    )


async def _add_application_artifact(
    *,
    uow: Any,
    id_generator: IdGenerator,
    case: PreparationCase,
    actor: UserId,
    artifact_type: ArtifactType,
    content: dict[str, Any],
    status: ArtifactStatus,
) -> PreparationArtifact:
    latest = await uow.artifacts.latest(case.id, artifact_type)
    version = latest.artifact_version + 1 if latest is not None else 1
    artifact = PreparationArtifact(
        id=ArtifactId(id_generator.new_uuid()),
        tenant_id=case.tenant_id,
        workspace_id=case.workspace_id,
        case_id=case.id,
        artifact_type=artifact_type,
        schema_version="1.0",
        artifact_version=version,
        status=status,
        content=content,
        created_by=actor,
        content_hash=_content_hash(content),
    )
    await uow.artifacts.add(artifact)
    return artifact
