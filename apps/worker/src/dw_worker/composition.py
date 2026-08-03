"""Worker composition root: wires the knowledge ingest pipeline from settings.

Mirrors the API's knowledge wiring but on the worker side, where the heavy
Docling+OCR parser lives. Only the composition root imports concrete adapters
(Clean/Hexagonal rule); consumers receive already-wired ports.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from dw_connectors.adapters.slack_approval_notifier import SlackApprovalNotifier
from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_knowledge.adapters.composite_parser import CompositeParser
from dw_knowledge.adapters.text_parser import PlaintextParser
from dw_knowledge.gateway import KnowledgeGateway
from dw_knowledge.ingest_jobs import IngestJobStore
from dw_knowledge.ports import DocumentParserPort, EmbeddingPort, ObjectStoragePort, VectorIndexPort
from dw_tender.adapters.preparation.notification_store import IntakeNotificationJobStore
from dw_worker.settings import WorkerSettings


@dataclass
class IngestComponents:
    engine: AsyncEngine
    gateway: KnowledgeGateway
    job_store: IngestJobStore
    parser: DocumentParserPort
    object_storage: ObjectStoragePort


@dataclass
class SlackApprovalComponents:
    engine: AsyncEngine
    store: IntakeNotificationJobStore
    notifier: SlackApprovalNotifier
    user_map: dict[str, str]
    web_base_url: str


def _build_storage(settings: WorkerSettings) -> ObjectStoragePort:
    from minio import Minio

    from dw_knowledge.adapters.minio_storage import MinioObjectStorageAdapter

    assert settings.s3_endpoint_url is not None
    endpoint = settings.s3_endpoint_url.replace("http://", "").replace("https://", "")
    client = Minio(
        endpoint,
        access_key=settings.s3_access_key or "",
        secret_key=settings.s3_secret_key or "",
        secure=settings.s3_endpoint_url.startswith("https://"),
    )
    return MinioObjectStorageAdapter(client=client, bucket=settings.s3_bucket)


def _build_embeddings(settings: WorkerSettings) -> EmbeddingPort:
    if settings.embedding_provider == "tei" and settings.embed_url:
        from dw_knowledge.adapters.tei_embedding import TeiEmbeddingAdapter

        return TeiEmbeddingAdapter(base_url=settings.embed_url, _dimension=settings.embed_dimension)
    from dw_knowledge.adapters.hash_embedding import HashEmbeddingAdapter

    return HashEmbeddingAdapter()


def _build_vector_index(settings: WorkerSettings) -> VectorIndexPort:
    if settings.qdrant_url:
        from qdrant_client import AsyncQdrantClient

        from dw_knowledge.adapters.qdrant_index import QdrantVectorIndexAdapter

        return QdrantVectorIndexAdapter(client=AsyncQdrantClient(url=settings.qdrant_url))
    from dw_knowledge.adapters.memory_index import InMemoryVectorIndexAdapter

    return InMemoryVectorIndexAdapter()


def _build_parser() -> DocumentParserPort:
    # Plaintext/Markdown handled cheaply; every richer format falls through to
    # Docling+OCR. Docling is imported lazily inside its adapter, so a missing
    # install only fails when a non-text file is actually parsed.
    parsers: list[DocumentParserPort] = [PlaintextParser()]
    try:
        from dw_knowledge.adapters.docling_parser import DoclingDocumentParser

        parsers.append(DoclingDocumentParser())
    except Exception:  # pragma: no cover - docling import is optional
        pass
    return CompositeParser(parsers=parsers)


def build_ingest_components(settings: WorkerSettings) -> IngestComponents | None:
    """Return wired ingest components, or ``None`` if infra is not configured."""
    if not (settings.database_url and settings.s3_endpoint_url):
        return None

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    clock = SystemClock()
    id_generator = Uuid4Generator()
    storage = _build_storage(settings)

    gateway = KnowledgeGateway(
        session_factory=session_factory,
        vector_index=_build_vector_index(settings),
        embeddings=_build_embeddings(settings),
        object_storage=storage,
        clock=clock,
        id_generator=id_generator,
    )
    job_store = IngestJobStore(
        session_factory=session_factory, clock=clock, id_generator=id_generator
    )
    return IngestComponents(
        engine=engine,
        gateway=gateway,
        job_store=job_store,
        parser=_build_parser(),
        object_storage=storage,
    )


def build_slack_approval_components(
    settings: WorkerSettings,
) -> SlackApprovalComponents | None:
    if not settings.slack_approvals_enabled:
        return None
    settings.validate_slack()
    assert settings.database_url is not None
    assert settings.slack_bot_token is not None
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    clock = SystemClock()
    return SlackApprovalComponents(
        engine=engine,
        store=IntakeNotificationJobStore(session_factory=session_factory, clock=clock),
        notifier=SlackApprovalNotifier(bot_token=settings.slack_bot_token),
        user_map=settings.slack_user_map(),
        web_base_url=settings.slack_web_base_url,
    )
