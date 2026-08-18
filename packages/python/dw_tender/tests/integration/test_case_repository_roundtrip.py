"""What the aggregate changes, the database must keep.

An amendment moves the demand itself — the figure, the deadline, the title.
The repository's UPDATE was written when those were fixed at creation and
listed only the workflow columns, so a case could report a new budget, bump
its version, and come back from the database with the old one. Nothing in the
unit tests could see it: their fake repository stores the object by reference,
so the "saved" case is the amended one whether or not any column was written.

This test round-trips through real SQL, which is the only place that lie shows.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[3] / "dw_agent_runtime" / "tests" / "integration"),
)
from runtime_harness import (
    RuntimeUrls,
    recreate_database,
    run_migrations,
    runtime_urls,
)

pytestmark = pytest.mark.integration

TENANT = uuid.uuid4()
WORKSPACE = uuid.uuid4()
ACTOR = uuid.uuid4()


@pytest.fixture(scope="module")
def urls() -> RuntimeUrls:
    resolved = runtime_urls()
    try:
        asyncio.run(recreate_database(resolved.admin))
    except Exception as exc:  # pragma: no cover - environment failure
        pytest.fail(f"Postgres unreachable — run `make infra-up`. Error: {exc}")
    result = run_migrations(resolved.migrator)
    assert result.returncode == 0, result.stderr
    return resolved


async def test_an_amended_demand_survives_the_round_trip(urls: RuntimeUrls) -> None:
    from dw_api.bootstrap import build_container
    from dw_api.settings import ApiSettings
    from dw_kernel.ids import TenantId, UserId, WorkspaceId
    from dw_tender.domain.preparation.entities import (
        BusinessDomain,
        CaseState,
        PreparationCase,
        ProcurementType,
    )
    from dw_tender.domain.value_objects.ids import PreparationCaseId

    container = build_container(
        ApiSettings(
            profile="test",
            database_url=urls.migrator,
            model_provider="mock",
            s3_endpoint_url=f"http://{urls.minio_endpoint}",
            s3_access_key=urls.minio_access_key,
            s3_secret_key=urls.minio_secret_key,
            qdrant_url=urls.qdrant_url,
            qdrant_collection="dw_knowledge_test",
        )
    )
    assert container.preparation is not None
    factory = container.preparation.uow_factory
    case_id = PreparationCaseId(uuid.uuid4())

    async with factory(TenantId(TENANT)) as uow:
        await uow.cases.add(
            PreparationCase(
                id=case_id,
                tenant_id=TenantId(TENANT),
                workspace_id=WorkspaceId(WORKSPACE),
                title="Mua 300 màn hình 27 inch",
                created_by=UserId(ACTOR),
                estimated_value_minor=12_000_000_000,
                deadline="60 ngày",
                procurement_type=ProcurementType.GOODS,
                business_domain=BusinessDomain.INFORMATION_TECHNOLOGY,
                state=CaseState.CP2_PENDING,
            )
        )
        await uow.commit()

    async with factory(TenantId(TENANT)) as uow:
        case = await uow.cases.get(case_id)
        assert case is not None
        case.estimated_value_minor = 15_000_000_000
        case.deadline = "120 ngày"
        case.version += 1
        await uow.cases.save(case)
        await uow.commit()

    async with factory(TenantId(TENANT)) as uow:
        reloaded = await uow.cases.get(case_id)
        assert reloaded is not None
        assert reloaded.estimated_value_minor == 15_000_000_000, "the figure was dropped on write"
        assert reloaded.deadline == "120 ngày"

    await container.shutdown()
