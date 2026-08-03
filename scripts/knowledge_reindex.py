"""Rebuild the Qdrant collection from the chunks stored in Postgres.

Use when the collection was created with a different embedding dimension
(e.g. hash-embedding 64d era) and searches fail with a dimension error —
documents/chunks in Postgres are the source of truth, vectors are derived.

Run INSIDE the api container (it has the wired gateway + TEI access):

    docker compose --env-file .env -f infra/compose/docker-compose.yml \
        exec -T api python - < scripts/knowledge_reindex.py
"""

from __future__ import annotations

import asyncio
from typing import Any

import sqlalchemy as sa

BATCH = 16


async def main() -> None:
    from dw_api import bootstrap
    from dw_knowledge import tables
    from dw_knowledge.ports import IndexableChunk

    container = bootstrap.build_container()
    gateway = container.knowledge_gateway
    assert gateway is not None, "knowledge gateway is not wired"
    # Concrete Qdrant adapter attrs (client/collection) — not on the port.
    index: Any = gateway.vector_index
    embeddings = gateway.embeddings
    print("embedding dimension:", embeddings.dimension)

    # 1) Drop the stale collection; ensure_ready recreates it at the right dim.
    try:
        await index.client.delete_collection(index.collection)
        print("dropped collection:", index.collection)
    except Exception as exc:  # first run / already gone
        print("drop skipped:", type(exc).__name__)
    gateway._ready = False
    await gateway.ensure_ready()
    print("collection recreated")

    # 2) Re-embed every current active chunk per tenant (RLS needs the GUC).
    async with gateway.session_factory() as session:
        tenants = (
            (await session.execute(sa.text("select distinct tenant_id from knowledge.documents")))
            .scalars()
            .all()
        )
    total = 0
    for tenant_id in tenants:
        async with gateway.session_factory() as session:
            await session.execute(
                sa.text("select set_config('app.tenant_id', :t, false)"),
                {"t": str(tenant_id)},
            )
            docs = (
                await session.execute(
                    sa.select(
                        tables.documents.c.id,
                        tables.documents.c.tenant_id,
                        tables.documents.c.workspace_id,
                        tables.documents.c.domain,
                        tables.documents.c.classification,
                        tables.documents.c.source_version,
                        tables.documents.c.index_version,
                        tables.documents.c.scope,
                        tables.documents.c.title,
                    ).where(
                        tables.documents.c.is_current,
                        tables.documents.c.status == "active",
                    )
                )
            ).all()
            print(f"tenant {tenant_id}: {len(docs)} documents")
            for doc in docs:
                chunk_rows = (
                    await session.execute(
                        sa.select(tables.chunks)
                        .where(tables.chunks.c.document_id == doc.id)
                        .order_by(tables.chunks.c.seq)
                    )
                ).all()
                if not chunk_rows:
                    print(" -", doc.title, ": no chunks, skipped")
                    continue
                texts: list[str] = []
                metas: list[str] = []
                for row in chunk_rows:
                    meta = row._mapping.get("metadata") or {}
                    section = str(meta.get("section_path", "") or "")
                    metas.append(section)
                    texts.append(f"{section}\n{row.content}" if section else row.content)
                vectors: list[tuple[float, ...]] = []
                for i in range(0, len(texts), BATCH):
                    vectors.extend(tuple(v) for v in await embeddings.embed(texts[i : i + BATCH]))
                await index.upsert(
                    [
                        IndexableChunk(
                            chunk_id=row.id,
                            document_id=doc.id,
                            tenant_id=doc.tenant_id,
                            workspace_id=doc.workspace_id,
                            domain=doc.domain,
                            content=row.content,
                            classification=doc.classification,
                            source_version=doc.source_version,
                            index_version=doc.index_version or "v1",
                            provenance_hash=row.provenance_hash,
                            acl_principals=("tenant:*",),
                            vector=vector,
                            section_path=section,
                            seq=row.seq,
                            scope=doc.scope,
                        )
                        for row, vector, section in zip(chunk_rows, vectors, metas, strict=True)
                    ]
                )
                total += len(chunk_rows)
                print(" -", doc.title, ":", len(chunk_rows), "chunks reindexed")
    print("TOTAL points:", total)


asyncio.run(main())
