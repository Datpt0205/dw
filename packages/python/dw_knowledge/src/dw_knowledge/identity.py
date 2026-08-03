"""Deterministic ids for documents/chunks → idempotent re-ingest & upsert.

Same logical document (tenant/workspace/domain/title/version) always maps to the
same ``document_id``; each chunk to the same ``chunk_id`` = uuid5(doc, index, seq).
Re-ingesting therefore OVERWRITES the same Postgres rows and Qdrant points instead
of creating duplicates — this is how we "find the exact chunk again" on update.
"""

from __future__ import annotations

import uuid

# Stable namespace for the knowledge plane (do not change — ids depend on it).
NAMESPACE = uuid.UUID("b6d1e6a2-3c4f-5a70-9b21-000000000d20")


def document_id_for(
    *,
    tenant_id: uuid.UUID,
    workspace_id: uuid.UUID,
    domain: str,
    title: str,
    source_version: str,
    scope: str = "tenant",
) -> uuid.UUID:
    key = f"doc:{scope}:{tenant_id}:{workspace_id}:{domain}:{title.strip()}:{source_version}"
    if scope == "global":
        # Global (e.g. legal) docs are identity-independent of the ingesting tenant.
        key = f"doc:global:{domain}:{title.strip()}:{source_version}"
    return uuid.uuid5(NAMESPACE, key)


def doc_key_for(
    *, tenant_id: uuid.UUID, workspace_id: uuid.UUID, domain: str, title: str, scope: str = "tenant"
) -> uuid.UUID:
    """Version-independent logical key: groups all versions of the same document
    so a new version can supersede the previous current one."""
    if scope == "global":
        return uuid.uuid5(NAMESPACE, f"dockey:global:{domain}:{title.strip()}")
    return uuid.uuid5(NAMESPACE, f"dockey:{tenant_id}:{workspace_id}:{domain}:{title.strip()}")


def chunk_id_for(*, document_id: uuid.UUID, index_version: str, seq: int) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"chunk:{document_id}:{index_version}:{seq}")
