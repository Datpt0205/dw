"""SQL persistence for DW01 preparation (RLS-scoped per transaction)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_kernel.errors import ConflictError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_tender.adapters.preparation import tables
from dw_tender.domain.preparation.entities import (
    ArtifactStatus,
    ArtifactType,
    CaseState,
    DocumentKind,
    PreparationArtifact,
    PreparationCase,
    PreparationDocument,
)
from dw_tender.domain.value_objects.ids import (
    ArtifactId,
    PreparationCaseId,
    PreparationDocumentId,
)

_SET_TENANT = text("SELECT set_config('app.tenant_id', :tenant_id, true)")


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _case_from_row(row: sa.Row) -> PreparationCase:
    return PreparationCase(
        id=PreparationCaseId(row.id),
        tenant_id=TenantId(row.tenant_id),
        workspace_id=WorkspaceId(row.workspace_id),
        title=row.title,
        created_by=UserId(row.created_by),
        source_pr_ref=row.source_pr_ref,
        description=row.description,
        estimated_value_minor=row.estimated_value_minor,
        currency=row.currency,
        deadline=row.deadline,
        owner_name=row.owner_name,
        method_key=row.method_key,
        state=CaseState(row.state),
        current_step=row.current_step,
        last_run_id=row.last_run_id,
        current_official_artifact_id=row.current_official_artifact_id,
        export_ref=row.export_ref,
        version=row.version,
    )


def _artifact_from_row(row: sa.Row) -> PreparationArtifact:
    return PreparationArtifact(
        id=ArtifactId(row.id),
        tenant_id=TenantId(row.tenant_id),
        workspace_id=WorkspaceId(row.workspace_id),
        case_id=PreparationCaseId(row.case_id),
        artifact_type=ArtifactType(row.artifact_type),
        schema_version=row.schema_version,
        artifact_version=row.artifact_version,
        status=ArtifactStatus(row.status),
        content=dict(row.content_json),
        created_by=UserId(row.created_by),
        evidence_refs=tuple(row.evidence_refs),
        source_artifact_ids=tuple(row.source_artifact_ids),
        content_hash=row.content_hash,
    )


@dataclass
class SqlPreparationCaseRepository:
    session: AsyncSession

    async def add(self, case: PreparationCase) -> None:
        await self.session.execute(
            sa.insert(tables.preparation_cases).values(
                id=case.id.value,
                tenant_id=case.tenant_id.value,
                workspace_id=case.workspace_id.value,
                title=case.title,
                description=case.description,
                source_pr_ref=case.source_pr_ref,
                estimated_value_minor=case.estimated_value_minor,
                currency=case.currency,
                deadline=case.deadline,
                owner_name=case.owner_name,
                method_key=case.method_key,
                state=case.state.value,
                current_step=case.current_step,
                created_by=case.created_by.value,
                version=case.version,
            )
        )

    async def get(self, case_id: PreparationCaseId) -> PreparationCase | None:
        row = (
            await self.session.execute(
                sa.select(tables.preparation_cases).where(
                    tables.preparation_cases.c.id == case_id.value
                )
            )
        ).first()
        return _case_from_row(row) if row is not None else None

    async def save(self, case: PreparationCase) -> None:
        result = await self.session.execute(
            sa.update(tables.preparation_cases)
            .where(
                tables.preparation_cases.c.id == case.id.value,
                tables.preparation_cases.c.version == case.version - 1,
            )
            .values(
                state=case.state.value,
                current_step=case.current_step,
                method_key=case.method_key,
                last_run_id=case.last_run_id,
                current_official_artifact_id=case.current_official_artifact_id,
                export_ref=case.export_ref,
                version=case.version,
                updated_at=_now(),
            )
        )
        assert isinstance(result, sa.CursorResult)
        if result.rowcount != 1:
            raise ConflictError(
                "preparation case was modified concurrently",
                details={"case_id": str(case.id.value)},
            )

    async def list_recent(self, limit: int = 50) -> list[PreparationCase]:
        rows = (
            await self.session.execute(
                sa.select(tables.preparation_cases)
                .order_by(tables.preparation_cases.c.created_at.desc())
                .limit(limit)
            )
        ).all()
        return [_case_from_row(row) for row in rows]


@dataclass
class SqlPreparationDocumentRepository:
    session: AsyncSession

    async def add(self, document: PreparationDocument) -> None:
        await self.session.execute(
            sa.insert(tables.preparation_documents).values(
                id=document.id.value,
                tenant_id=document.tenant_id.value,
                workspace_id=document.workspace_id.value,
                case_id=document.case_id.value,
                kind=document.kind.value,
                title=document.title,
                storage_key=document.storage_key,
                content_hash=document.content_hash,
                uploaded_by=document.uploaded_by.value,
            )
        )

    async def list_for_case(self, case_id: PreparationCaseId) -> list[PreparationDocument]:
        rows = (
            await self.session.execute(
                sa.select(tables.preparation_documents).where(
                    tables.preparation_documents.c.case_id == case_id.value
                )
            )
        ).all()
        return [
            PreparationDocument(
                id=PreparationDocumentId(row.id),
                tenant_id=TenantId(row.tenant_id),
                workspace_id=WorkspaceId(row.workspace_id),
                case_id=PreparationCaseId(row.case_id),
                kind=DocumentKind(row.kind),
                title=row.title,
                storage_key=row.storage_key,
                content_hash=row.content_hash,
                uploaded_by=UserId(row.uploaded_by),
            )
            for row in rows
        ]


@dataclass
class SqlPreparationArtifactRepository:
    session: AsyncSession

    async def add(self, artifact: PreparationArtifact) -> None:
        await self.session.execute(
            sa.insert(tables.preparation_artifacts).values(
                id=artifact.id.value,
                tenant_id=artifact.tenant_id.value,
                workspace_id=artifact.workspace_id.value,
                case_id=artifact.case_id.value,
                artifact_type=artifact.artifact_type.value,
                schema_version=artifact.schema_version,
                artifact_version=artifact.artifact_version,
                status=artifact.status.value,
                content_json=artifact.content,
                evidence_refs=list(artifact.evidence_refs),
                source_artifact_ids=list(artifact.source_artifact_ids),
                content_hash=artifact.content_hash,
                created_by=artifact.created_by.value,
            )
        )

    async def get(self, artifact_id: ArtifactId) -> PreparationArtifact | None:
        row = (
            await self.session.execute(
                sa.select(tables.preparation_artifacts).where(
                    tables.preparation_artifacts.c.id == artifact_id.value
                )
            )
        ).first()
        return _artifact_from_row(row) if row is not None else None

    async def list_for_case(self, case_id: PreparationCaseId) -> list[PreparationArtifact]:
        rows = (
            await self.session.execute(
                sa.select(tables.preparation_artifacts)
                .where(tables.preparation_artifacts.c.case_id == case_id.value)
                .order_by(tables.preparation_artifacts.c.created_at.asc())
            )
        ).all()
        return [_artifact_from_row(row) for row in rows]

    async def latest(
        self, case_id: PreparationCaseId, artifact_type: ArtifactType
    ) -> PreparationArtifact | None:
        row = (
            await self.session.execute(
                sa.select(tables.preparation_artifacts)
                .where(
                    tables.preparation_artifacts.c.case_id == case_id.value,
                    tables.preparation_artifacts.c.artifact_type == artifact_type.value,
                )
                .order_by(tables.preparation_artifacts.c.artifact_version.desc())
                .limit(1)
            )
        ).first()
        return _artifact_from_row(row) if row is not None else None

    async def mark_official(self, artifact_id: ArtifactId) -> None:
        await self.session.execute(
            sa.update(tables.preparation_artifacts)
            .where(tables.preparation_artifacts.c.id == artifact_id.value)
            .values(status=ArtifactStatus.OFFICIAL.value, approved_at=_now())
        )


class SqlPreparationUnitOfWork:
    cases: SqlPreparationCaseRepository
    documents: SqlPreparationDocumentRepository
    artifacts: SqlPreparationArtifactRepository

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], tenant_id: TenantId
    ) -> None:
        self._session_factory = session_factory
        self._tenant_id = tenant_id
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> SqlPreparationUnitOfWork:
        self._session = self._session_factory()
        await self._session.begin()
        await self._session.execute(_SET_TENANT, {"tenant_id": str(self._tenant_id.value)})
        self.cases = SqlPreparationCaseRepository(self._session)
        self.documents = SqlPreparationDocumentRepository(self._session)
        self.artifacts = SqlPreparationArtifactRepository(self._session)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
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
class SqlPreparationUnitOfWorkFactory:
    session_factory: async_sessionmaker[AsyncSession]

    def __call__(self, tenant_id: TenantId) -> SqlPreparationUnitOfWork:
        return SqlPreparationUnitOfWork(self.session_factory, tenant_id)
