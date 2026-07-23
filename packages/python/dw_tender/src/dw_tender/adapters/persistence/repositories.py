"""Tender SQL repositories + UnitOfWork (SET LOCAL tenant context)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from types import TracebackType

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_kernel.errors import ConflictError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_tender.adapters.persistence import tables
from dw_tender.application.ports import (
    FindingRepositoryPort,
    RecommendationRepositoryPort,
    RequirementRepositoryPort,
    TenderCaseRepositoryPort,
    TenderDocumentRepositoryPort,
)
from dw_tender.domain.entities import (
    CaseStatus,
    ComplianceFinding,
    DocumentKind,
    FindingStatus,
    Requirement,
    TenderCase,
    TenderDocument,
    TenderRecommendation,
)
from dw_tender.domain.value_objects.ids import RequirementId, TenderCaseId
from dw_tender.domain.value_objects.scoring import RequirementKind

_SET_TENANT = text("SELECT set_config('app.tenant_id', :tenant_id, true)")


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _case_from_row(row: Row[tuple]) -> TenderCase:  # type: ignore[type-arg]
    return TenderCase(
        id=TenderCaseId(row.id),
        tenant_id=TenantId(row.tenant_id),
        workspace_id=WorkspaceId(row.workspace_id),
        title=row.title,
        description=row.description,
        created_by=UserId(row.created_by),
        status=CaseStatus(row.status),
        last_run_id=row.last_run_id,
        export_ref=row.export_ref,
        version=row.version,
    )


@dataclass
class SqlTenderCaseRepository(TenderCaseRepositoryPort):
    session: AsyncSession

    async def add(self, case: TenderCase) -> None:
        await self.session.execute(
            sa.insert(tables.cases).values(
                id=case.id.value,
                tenant_id=case.tenant_id.value,
                workspace_id=case.workspace_id.value,
                title=case.title,
                description=case.description,
                status=case.status.value,
                last_run_id=case.last_run_id,
                export_ref=case.export_ref,
                created_by=case.created_by.value,
                version=case.version,
                created_at=_now(),
                updated_at=_now(),
            )
        )

    async def get(self, case_id: TenderCaseId) -> TenderCase | None:
        row = (
            await self.session.execute(
                sa.select(tables.cases).where(tables.cases.c.id == case_id.value)
            )
        ).first()
        return _case_from_row(row) if row else None

    async def save(self, case: TenderCase) -> None:
        result = await self.session.execute(
            sa.update(tables.cases)
            .where(
                tables.cases.c.id == case.id.value,
                tables.cases.c.version == case.version - 1,
            )
            .values(
                status=case.status.value,
                last_run_id=case.last_run_id,
                export_ref=case.export_ref,
                version=case.version,
                updated_at=_now(),
            )
        )
        assert isinstance(result, sa.CursorResult)
        if result.rowcount != 1:
            raise ConflictError(
                "tender case was modified concurrently", details={"case_id": str(case.id)}
            )

    async def list_recent(self, limit: int = 50) -> list[TenderCase]:
        rows = await self.session.execute(
            sa.select(tables.cases).order_by(tables.cases.c.created_at.desc()).limit(limit)
        )
        return [_case_from_row(row) for row in rows]


@dataclass
class SqlTenderDocumentRepository(TenderDocumentRepositoryPort):
    session: AsyncSession

    async def add(self, document: TenderDocument) -> None:
        await self.session.execute(
            sa.insert(tables.documents).values(
                id=document.id,
                tenant_id=document.tenant_id.value,
                workspace_id=document.workspace_id.value,
                case_id=document.case_id.value,
                kind=document.kind.value,
                title=document.title,
                supplier_name=document.supplier_name,
                storage_key=document.storage_key,
                content_hash=document.content_hash,
                knowledge_document_id=document.knowledge_document_id,
                created_at=_now(),
            )
        )

    async def list_for_case(self, case_id: TenderCaseId) -> list[TenderDocument]:
        rows = await self.session.execute(
            sa.select(tables.documents)
            .where(tables.documents.c.case_id == case_id.value)
            .order_by(tables.documents.c.created_at)
        )
        return [
            TenderDocument(
                id=row.id,
                tenant_id=TenantId(row.tenant_id),
                workspace_id=WorkspaceId(row.workspace_id),
                case_id=TenderCaseId(row.case_id),
                kind=DocumentKind(row.kind),
                title=row.title,
                storage_key=row.storage_key,
                content_hash=row.content_hash,
                supplier_name=row.supplier_name,
                knowledge_document_id=row.knowledge_document_id,
            )
            for row in rows
        ]

    async def set_knowledge_document(
        self, document_id: uuid.UUID, knowledge_document_id: uuid.UUID
    ) -> None:
        await self.session.execute(
            sa.update(tables.documents)
            .where(tables.documents.c.id == document_id)
            .values(knowledge_document_id=knowledge_document_id)
        )


@dataclass
class SqlRequirementRepository(RequirementRepositoryPort):
    session: AsyncSession

    async def replace_for_case(
        self, case_id: TenderCaseId, requirements: list[Requirement]
    ) -> None:
        await self.session.execute(
            sa.delete(tables.requirements).where(tables.requirements.c.case_id == case_id.value)
        )
        for requirement in requirements:
            await self.session.execute(
                sa.insert(tables.requirements).values(
                    id=requirement.id.value,
                    tenant_id=requirement.tenant_id.value,
                    workspace_id=requirement.workspace_id.value,
                    case_id=requirement.case_id.value,
                    code=requirement.code,
                    statement=requirement.statement,
                    kind=requirement.kind.value,
                    weight=requirement.weight,
                )
            )

    async def list_for_case(self, case_id: TenderCaseId) -> list[Requirement]:
        rows = await self.session.execute(
            sa.select(tables.requirements)
            .where(tables.requirements.c.case_id == case_id.value)
            .order_by(tables.requirements.c.code)
        )
        return [
            Requirement(
                id=RequirementId(row.id),
                tenant_id=TenantId(row.tenant_id),
                workspace_id=WorkspaceId(row.workspace_id),
                case_id=TenderCaseId(row.case_id),
                code=row.code,
                statement=row.statement,
                kind=RequirementKind(row.kind),
                weight=Decimal(row.weight),
            )
            for row in rows
        ]


@dataclass
class SqlFindingRepository(FindingRepositoryPort):
    session: AsyncSession

    async def replace_for_case(
        self, case_id: TenderCaseId, findings: list[ComplianceFinding]
    ) -> None:
        await self.session.execute(
            sa.delete(tables.compliance_findings).where(
                tables.compliance_findings.c.case_id == case_id.value
            )
        )
        for finding in findings:
            await self.session.execute(
                sa.insert(tables.compliance_findings).values(
                    id=finding.id,
                    tenant_id=finding.tenant_id.value,
                    workspace_id=finding.workspace_id.value,
                    case_id=finding.case_id.value,
                    requirement_code=finding.requirement_code,
                    supplier_name=finding.supplier_name,
                    status=finding.status.value,
                    raw_score=finding.raw_score,
                    note=finding.note,
                    evidence=list(finding.evidence),
                )
            )

    async def list_for_case(self, case_id: TenderCaseId) -> list[ComplianceFinding]:
        rows = await self.session.execute(
            sa.select(tables.compliance_findings)
            .where(tables.compliance_findings.c.case_id == case_id.value)
            .order_by(
                tables.compliance_findings.c.supplier_name,
                tables.compliance_findings.c.requirement_code,
            )
        )
        return [
            ComplianceFinding(
                id=row.id,
                tenant_id=TenantId(row.tenant_id),
                workspace_id=WorkspaceId(row.workspace_id),
                case_id=TenderCaseId(row.case_id),
                requirement_code=row.requirement_code,
                supplier_name=row.supplier_name,
                status=FindingStatus(row.status),
                raw_score=Decimal(row.raw_score),
                note=row.note,
                evidence=tuple(row.evidence),
            )
            for row in rows
        ]


@dataclass
class SqlRecommendationRepository(RecommendationRepositoryPort):
    session: AsyncSession

    async def upsert(self, recommendation: TenderRecommendation) -> None:
        statement = sa.dialects.postgresql.insert(tables.recommendations).values(
            id=recommendation.id,
            tenant_id=recommendation.tenant_id.value,
            workspace_id=recommendation.workspace_id.value,
            case_id=recommendation.case_id.value,
            recommended_supplier=recommendation.recommended_supplier,
            rationale=recommendation.rationale,
            supplier_scores=recommendation.supplier_scores,
            risks=recommendation.risks,
            evidence=recommendation.evidence,
            gate_passed=recommendation.gate_passed,
            gate_violations=recommendation.gate_violations,
            scoring_policy_version=recommendation.scoring_policy_version,
            confidence=recommendation.confidence,
            created_at=_now(),
        )
        await self.session.execute(
            statement.on_conflict_do_update(
                index_elements=["case_id"],
                set_={
                    "recommended_supplier": statement.excluded.recommended_supplier,
                    "rationale": statement.excluded.rationale,
                    "supplier_scores": statement.excluded.supplier_scores,
                    "risks": statement.excluded.risks,
                    "evidence": statement.excluded.evidence,
                    "gate_passed": statement.excluded.gate_passed,
                    "gate_violations": statement.excluded.gate_violations,
                    "scoring_policy_version": statement.excluded.scoring_policy_version,
                    "confidence": statement.excluded.confidence,
                },
            )
        )

    async def get_for_case(self, case_id: TenderCaseId) -> TenderRecommendation | None:
        row = (
            await self.session.execute(
                sa.select(tables.recommendations).where(
                    tables.recommendations.c.case_id == case_id.value
                )
            )
        ).first()
        if row is None:
            return None
        return TenderRecommendation(
            id=row.id,
            tenant_id=TenantId(row.tenant_id),
            workspace_id=WorkspaceId(row.workspace_id),
            case_id=TenderCaseId(row.case_id),
            scoring_policy_version=row.scoring_policy_version,
            recommended_supplier=row.recommended_supplier,
            rationale=row.rationale,
            supplier_scores=list(row.supplier_scores),
            risks=list(row.risks),
            evidence=list(row.evidence),
            gate_passed=row.gate_passed,
            gate_violations=list(row.gate_violations),
            confidence=row.confidence,
        )


class SqlTenderUnitOfWork:
    """Implements ``TenderUnitOfWork``."""

    cases: TenderCaseRepositoryPort
    documents: TenderDocumentRepositoryPort
    requirements: RequirementRepositoryPort
    findings: FindingRepositoryPort
    recommendations: RecommendationRepositoryPort

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], tenant_id: TenantId
    ) -> None:
        self._session_factory = session_factory
        self._tenant_id = tenant_id
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> SqlTenderUnitOfWork:
        self._session = self._session_factory()
        await self._session.begin()
        await self._session.execute(_SET_TENANT, {"tenant_id": str(self._tenant_id)})
        self.cases = SqlTenderCaseRepository(self._session)
        self.documents = SqlTenderDocumentRepository(self._session)
        self.requirements = SqlRequirementRepository(self._session)
        self.findings = SqlFindingRepository(self._session)
        self.recommendations = SqlRecommendationRepository(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        assert self._session is not None
        try:
            if exc_type is not None:
                await self._session.rollback()
        finally:
            await self._session.close()
            self._session = None

    async def commit(self) -> None:
        assert self._session is not None
        await self._session.commit()

    async def rollback(self) -> None:
        assert self._session is not None
        await self._session.rollback()


@dataclass(frozen=True)
class SqlTenderUnitOfWorkFactory:
    session_factory: async_sessionmaker[AsyncSession]

    def __call__(self, tenant_id: TenantId) -> SqlTenderUnitOfWork:
        return SqlTenderUnitOfWork(self.session_factory, tenant_id)
