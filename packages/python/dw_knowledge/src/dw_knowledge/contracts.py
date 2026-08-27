"""Evidence and retrieval contracts (blueprint §13).

``SearchQuery`` deliberately has NO tenant/workspace/ACL fields: callers cannot
supply them. The retrieval gateway injects mandatory filters from the trusted
``AccessContext`` — that asymmetry is the security boundary.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Classification = str  # "internal" | "confidential" | "restricted" (validated by policy)


class EvidenceRef(BaseModel):
    """Provenance-carrying reference to a chunk of source material (§13.4)."""

    model_config = ConfigDict(frozen=True)

    evidence_id: UUID
    source_document_id: UUID
    source_version: str
    chunk_id: UUID | None = None
    page: int | None = Field(default=None, ge=1)
    start_offset: int | None = Field(default=None, ge=0)
    end_offset: int | None = Field(default=None, ge=0)
    quote: str | None = None
    # Where a reader could go to check this. The indexed corpus identifies a
    # document by id and looks its title up in the database; a page fetched from
    # the open web has no row to look up, so it carries its own name and URL —
    # and a citation nobody can follow is not a citation.
    source_title: str | None = None
    source_uri: str | None = None
    relevance_score: float = Field(ge=0.0, le=1.0)
    classification: Classification
    provenance_hash: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")


class SearchQuery(BaseModel):
    """Caller-controllable part of a retrieval request.

    Tenant, workspace and ACL constraints are intentionally absent — the
    knowledge gateway derives them from ``AccessContext`` and callers (including
    model output) can never override them.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(min_length=1)
    domain: str = "shared"
    top_k: int = Field(default=8, ge=1, le=50)
    document_ids: tuple[UUID, ...] = ()
    min_relevance: float = Field(default=0.0, ge=0.0, le=1.0)


class EvidenceChunk(BaseModel):
    """A retrieved chunk plus its evidence reference."""

    model_config = ConfigDict(frozen=True)

    content: str
    evidence: EvidenceRef
