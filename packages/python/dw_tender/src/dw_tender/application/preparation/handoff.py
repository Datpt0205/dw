"""Hand the sealed DW01 package to DW02 without anyone copying a file.

CP4 already seals an evaluation handoff: the official package, the submissions,
the artifact index with versions and hashes. Everything DW02 needs was sitting
in storage waiting for a human to fetch it. This carries it across, and records
on the DW01 case which evaluation it became — so "what happened to this tender"
is answerable from either side.

Nothing is re-derived on the way: the RFQ handed over is the package that was
made official, not a fresh render of the current state.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from dw_kernel.errors import ConflictError, DomainError, NotFoundError
from dw_kernel.ids import TenantId, UserId
from dw_kernel.ports import IdGenerator
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_tender.application.handlers import (
    AnalyzeCaseHandler,
    CreateTenderCaseCommand,
    CreateTenderCaseHandler,
    DocumentUpload,
)
from dw_tender.application.ports import DocumentStoragePort
from dw_tender.application.preparation.handlers import _add_application_artifact
from dw_tender.application.preparation.ports import PreparationUnitOfWorkFactory
from dw_tender.domain.entities import DocumentKind as EvaluationDocumentKind
from dw_tender.domain.preparation.entities import ArtifactStatus, ArtifactType, CaseState
from dw_tender.domain.preparation.entities import DocumentKind as PreparationDocumentKind
from dw_tender.domain.value_objects.ids import PreparationCaseId


@dataclass(frozen=True, slots=True)
class HandoffResult:
    evaluation_case_id: uuid.UUID
    run_id: uuid.UUID | None
    supplier_count: int
    # Submissions whose bytes are not text (a scanned PDF, a zip). They are
    # still handed over as a stub naming the file and its hash, because a
    # supplier silently missing from the evaluation is the worse failure.
    unreadable: tuple[str, ...]
    reused: bool


@dataclass
class HandoffToEvaluationHandler:
    uow_factory: PreparationUnitOfWorkFactory
    storage: DocumentStoragePort
    authorization: ScopeAuthorizationService
    id_generator: IdGenerator
    create_evaluation_case: CreateTenderCaseHandler
    analyze_case: AnalyzeCaseHandler | None = None

    async def handle(
        self, case_id: uuid.UUID, context: AccessContext, *, start_evaluation: bool = True
    ) -> HandoffResult:
        await self.authorization.require(
            context=context,
            action="tender.write",
            resource_type="preparation_case",
            resource_id=str(case_id),
        )
        async with self.uow_factory(TenantId(context.tenant_id)) as uow:
            case = await uow.cases.get(PreparationCaseId(case_id))
            if case is None:
                raise NotFoundError("preparation case not found", details={"case_id": str(case_id)})
            if case.state is not CaseState.COMPLETED:
                raise ConflictError(
                    "the package is not sealed yet — CP4 must complete first",
                    details={"case_id": str(case_id), "state": case.state.value},
                )
            handoff = await uow.artifacts.latest(case.id, ArtifactType.EVALUATION_HANDOFF)
            if handoff is None:
                raise ConflictError(
                    "no evaluation handoff on this case", details={"case_id": str(case_id)}
                )
            existing = handoff.content.get("evaluation_case_id")
            if existing:
                # Already handed over. Creating a second evaluation of the same
                # tender would give two answers to one question.
                return HandoffResult(
                    evaluation_case_id=uuid.UUID(str(existing)),
                    run_id=None,
                    supplier_count=int(str(handoff.content.get("submission_count", 0) or 0)),
                    unreadable=(),
                    reused=True,
                )
            manifest = await uow.artifacts.latest(case.id, ArtifactType.OFFICIAL_PACKAGE_MANIFEST)
            register = await uow.artifacts.latest(case.id, ArtifactType.SUBMISSION_REGISTER)
            documents = await uow.documents.list_for_case(case.id)
            title = case.title

        # DW02 groups the comparison by supplier, and the supplier's name lives
        # on the receiving register, not on the file.
        supplier_of: dict[str, str] = {}
        if register is not None:
            raw_items = register.content.get("items")
            for item in raw_items if isinstance(raw_items, list) else []:
                if isinstance(item, dict) and item.get("submission_id"):
                    supplier_of[str(item["submission_id"])] = str(item.get("supplier_name", ""))

        package_markdown = str((manifest.content.get("package_markdown") if manifest else "") or "")
        if not package_markdown.strip():
            raise ConflictError(
                "the official package has no readable content to hand over",
                details={"case_id": str(case_id)},
            )
        submissions = [
            doc for doc in documents if doc.kind is PreparationDocumentKind.SUPPLIER_SUBMISSION
        ]
        if not submissions:
            raise DomainError("no supplier submission to evaluate")

        uploads: list[DocumentUpload] = [
            DocumentUpload(
                kind=EvaluationDocumentKind.RFQ,
                title=f"HSMT chính thức — {title}",
                content=package_markdown,
            )
        ]
        unreadable: list[str] = []
        for doc in submissions:
            text = await self._read_text(doc.storage_key)
            if text is None:
                unreadable.append(doc.filename)
                text = (
                    f"[Không đọc được nội dung dạng văn bản: {doc.filename}, "
                    f"hash {doc.content_hash[:16]}. Hồ sơ vẫn được ghi nhận; "
                    "cần người đánh giá mở tệp gốc.]"
                )
            uploads.append(
                DocumentUpload(
                    kind=EvaluationDocumentKind.SUPPLIER_SUBMISSION,
                    title=doc.title or doc.filename,
                    content=text,
                    supplier_name=supplier_of.get(str(doc.id.value)) or None,
                )
            )

        evaluation_case_id = await self.create_evaluation_case.handle(
            CreateTenderCaseCommand(
                title=title,
                description=f"Đánh giá hồ sơ dự thầu — bàn giao từ DW01 case {case_id}",
                documents=tuple(uploads),
            ),
            context,
        )

        async with self.uow_factory(TenantId(context.tenant_id)) as uow:
            case = await uow.cases.get(PreparationCaseId(case_id))
            assert case is not None
            latest = await uow.artifacts.latest(case.id, ArtifactType.EVALUATION_HANDOFF)
            assert latest is not None
            await _add_application_artifact(
                uow=uow,
                id_generator=self.id_generator,
                case=case,
                actor=UserId(context.principal_id),
                artifact_type=ArtifactType.EVALUATION_HANDOFF,
                content={
                    **latest.content,
                    "evaluation_case_id": str(evaluation_case_id),
                    "handed_over_documents": len(uploads),
                    "unreadable_submissions": unreadable,
                },
                status=ArtifactStatus.OFFICIAL,
            )
            await uow.commit()

        run_id = None
        if start_evaluation and self.analyze_case is not None:
            run_id = await self.analyze_case.handle(evaluation_case_id, context)
        return HandoffResult(
            evaluation_case_id=evaluation_case_id,
            run_id=run_id,
            supplier_count=len(submissions),
            unreadable=tuple(unreadable),
            reused=False,
        )

    async def _read_text(self, storage_key: str) -> str | None:
        try:
            raw = await self.storage.get_object(storage_key)
        except Exception:
            return None
        try:
            text: str = bytes(raw).decode("utf-8")
        except UnicodeDecodeError:
            return None
        # A decoded blob full of control characters is not text either.
        printable = sum(1 for ch in text[:2000] if ch.isprintable() or ch in "\n\r\t")
        if not text.strip() or printable < len(text[:2000]) * 0.9:
            return None
        return text
