"""API view models for the DW01 preparation slice."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from dw_tender.domain.preparation.entities import PreparationArtifact, PreparationCase


class ArtifactView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    artifact_type: str
    artifact_version: int
    status: str
    content: dict[str, Any]
    content_hash: str

    @classmethod
    def from_domain(cls, artifact: PreparationArtifact) -> ArtifactView:
        return cls(
            id=artifact.id.value,
            artifact_type=artifact.artifact_type.value,
            artifact_version=artifact.artifact_version,
            status=artifact.status.value,
            content=artifact.content,
            content_hash=artifact.content_hash,
        )


class PreparationCaseView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    title: str
    description: str
    source_pr_ref: str
    estimated_value_minor: int
    currency: str
    deadline: str | None
    owner_name: str
    method_key: str | None
    state: str
    current_step: str
    last_run_id: UUID | None
    export_ref: str | None
    current_official_artifact_id: UUID | None
    version: int
    artifacts: list[ArtifactView] = []

    @classmethod
    def from_domain(
        cls,
        case: PreparationCase,
        artifacts: list[PreparationArtifact] | None = None,
    ) -> PreparationCaseView:
        return cls(
            id=case.id.value,
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
            last_run_id=case.last_run_id,
            export_ref=case.export_ref,
            current_official_artifact_id=case.current_official_artifact_id,
            version=case.version,
            artifacts=[ArtifactView.from_domain(a) for a in (artifacts or [])],
        )
