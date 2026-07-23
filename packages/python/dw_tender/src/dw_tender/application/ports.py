"""Tender application ports."""

from __future__ import annotations

import uuid
from types import TracebackType
from typing import Protocol

from dw_kernel.ids import TenantId
from dw_tender.domain.entities import (
    ComplianceFinding,
    Requirement,
    TenderCase,
    TenderDocument,
    TenderRecommendation,
)
from dw_tender.domain.value_objects.ids import TenderCaseId


class TenderCaseRepositoryPort(Protocol):
    async def add(self, case: TenderCase) -> None: ...

    async def get(self, case_id: TenderCaseId) -> TenderCase | None: ...

    async def save(self, case: TenderCase) -> None: ...

    async def list_recent(self, limit: int = 50) -> list[TenderCase]: ...


class TenderDocumentRepositoryPort(Protocol):
    async def add(self, document: TenderDocument) -> None: ...

    async def list_for_case(self, case_id: TenderCaseId) -> list[TenderDocument]: ...

    async def set_knowledge_document(
        self, document_id: uuid.UUID, knowledge_document_id: uuid.UUID
    ) -> None: ...


class RequirementRepositoryPort(Protocol):
    async def replace_for_case(
        self, case_id: TenderCaseId, requirements: list[Requirement]
    ) -> None: ...

    async def list_for_case(self, case_id: TenderCaseId) -> list[Requirement]: ...


class FindingRepositoryPort(Protocol):
    async def replace_for_case(
        self, case_id: TenderCaseId, findings: list[ComplianceFinding]
    ) -> None: ...

    async def list_for_case(self, case_id: TenderCaseId) -> list[ComplianceFinding]: ...


class RecommendationRepositoryPort(Protocol):
    async def upsert(self, recommendation: TenderRecommendation) -> None: ...

    async def get_for_case(self, case_id: TenderCaseId) -> TenderRecommendation | None: ...


class TenderUnitOfWork(Protocol):
    cases: TenderCaseRepositoryPort
    documents: TenderDocumentRepositoryPort
    requirements: RequirementRepositoryPort
    findings: FindingRepositoryPort
    recommendations: RecommendationRepositoryPort

    async def __aenter__(self) -> TenderUnitOfWork: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class TenderUnitOfWorkFactory(Protocol):
    def __call__(self, tenant_id: TenantId) -> TenderUnitOfWork: ...


class DocumentStoragePort(Protocol):
    async def put_object(self, key: str, data: bytes, content_type: str) -> str: ...

    async def get_object(self, key: str) -> bytes: ...
