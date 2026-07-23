"""E2E tender slice: documents → analyze → matrix + deterministic scoring →
recommendation with evidence → approval pause/resume → evaluation pack export.

Real stack: production composition root, Postgres, MinIO, Qdrant (via bootstrap
when QDRANT_URL set) and the deterministic mock model.
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path

import httpx
import pytest
from asgi_lifespan import LifespanManager

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[3] / "dw_agent_runtime" / "tests" / "integration"),
)
from runtime_harness import (
    REPO_ROOT,
    RuntimeUrls,
    load_env,
    recreate_database,
    run_migrations,
    runtime_urls,
)

pytestmark = [pytest.mark.integration, pytest.mark.e2e]

DEV_SECRET = "e2e-tender-secret-0123456789abcdef"
FIXTURES = REPO_ROOT / "db" / "fixtures" / "tender"
RFQ = (FIXTURES / "rfq_vat_tu_q3.txt").read_text(encoding="utf-8")
SUBMISSION_A = (FIXTURES / "chao_gia_thiet_bi_viet.txt").read_text(encoding="utf-8")
SUBMISSION_B = (FIXTURES / "chao_gia_vat_tu_mien_nam.txt").read_text(encoding="utf-8")

SUPPLIER_A = "Công ty TNHH Thiết bị Việt"
SUPPLIER_B = "Công ty CP Vật tư Miền Nam"

SEED_NAMESPACE = uuid.UUID("6f0f6f1e-9f6a-4f65-9a1c-000000000d10")


def sid(kind: str, key: str) -> uuid.UUID:
    return uuid.uuid5(SEED_NAMESPACE, f"{kind}:{key}")


def run_seed(database_url: str) -> None:
    import os
    import subprocess

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "seed_demo.py")],
        env={**os.environ, "DW_DATABASE_URL": database_url},
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.fixture(scope="session")
def urls() -> RuntimeUrls:
    resolved = runtime_urls()
    try:
        asyncio.run(recreate_database(resolved.admin))
    except Exception as exc:
        pytest.fail(f"Postgres unreachable — run `make infra-up`. Error: {exc}")
    result = run_migrations(resolved.migrator)
    if result.returncode != 0:
        pytest.fail(f"alembic upgrade failed:\n{result.stderr}")
    run_seed(resolved.migrator)
    return resolved


@pytest.fixture
async def client(urls: RuntimeUrls):
    from dw_api.bootstrap import build_container
    from dw_api.main import create_app
    from dw_api.settings import ApiSettings

    env = load_env()
    settings = ApiSettings(
        profile="test",
        database_url=urls.app,
        auth_mode="dev",
        dev_secret=DEV_SECRET,
        s3_endpoint_url=f"http://{urls.minio_endpoint}",
        s3_access_key=urls.minio_access_key,
        s3_secret_key=urls.minio_secret_key,
        s3_bucket=env.get("S3_BUCKET_ARTIFACTS", "dw-artifacts"),
        qdrant_url=urls.qdrant_url,
        model_provider="mock",
    )
    container = build_container(settings)
    assert container.tender is not None, "tender slice must be wired"
    app = create_app(container)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", timeout=120
        ) as http:
            yield http


def headers(subject: str, tenant_slug: str = "tenant-alpha") -> dict[str, str]:
    from dw_platform.adapters.identity.dev_token import DevTokenVerifier

    token = DevTokenVerifier(DEV_SECRET).issue(subject)
    return {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Id": str(sid("tenant", tenant_slug)),
        "X-Workspace-Id": str(sid("workspace", f"{tenant_slug}:main")),
    }


CASE_BODY = {
    "title": "RFQ vật tư sản xuất quý 3/2026",
    "description": "Lựa chọn nhà cung cấp vật tư nhóm A",
    "documents": [
        {"kind": "rfq", "title": "RFQ vật tư Q3", "content": RFQ},
        {
            "kind": "supplier_submission",
            "title": "Chào giá Thiết bị Việt",
            "content": SUBMISSION_A,
            "supplier_name": SUPPLIER_A,
        },
        {
            "kind": "supplier_submission",
            "title": "Chào giá Vật tư Miền Nam",
            "content": SUBMISSION_B,
            "supplier_name": SUPPLIER_B,
        },
    ],
}


async def _create_and_analyze(client: httpx.AsyncClient, member: dict[str, str]) -> tuple[str, str]:
    created = await client.post("/api/v1/procurement/cases", headers=member, json=CASE_BODY)
    assert created.status_code == 201, created.text
    case_id = created.json()["case_id"]
    analyzed = await client.post(f"/api/v1/procurement/cases/{case_id}/analyze", headers=member)
    assert analyzed.status_code == 202, analyzed.text
    return case_id, analyzed.json()["run_id"]


async def test_tender_end_to_end(client: httpx.AsyncClient) -> None:
    member = headers("dev|an.nguyen")
    approver = headers("dev|binh.tran")

    case_id, run_id = await _create_and_analyze(client, member)

    # paused at approval with recommendation ready
    run = (await client.get(f"/api/v1/runs/{run_id}", headers=member)).json()
    assert run["status"] == "waiting_approval", run
    approval_id = run["approval_request_id"]
    # every run records the release it was produced by (§23)
    assert run["release_manifest_ref"], "run must carry a release manifest reference"

    case = (await client.get(f"/api/v1/procurement/cases/{case_id}", headers=member)).json()
    assert case["status"] == "recommendation_ready"
    assert len(case["requirements"]) == 4
    assert len(case["findings"]) == 8

    rec = case["recommendation"]
    assert rec is not None
    # Deterministic golden numbers: A 87.00 eligible; B disqualified (mandatory fail).
    scores = {s["supplier_name"]: s for s in rec["supplier_scores"]}
    assert scores[SUPPLIER_A]["total_score"] == "87.00"
    assert scores[SUPPLIER_A]["eligible"] is True
    assert scores[SUPPLIER_B]["mandatory_passed"] is False
    assert scores[SUPPLIER_B]["eligible"] is False
    assert rec["recommended_supplier"] == SUPPLIER_A
    assert rec["gate_passed"] is True
    assert rec["evidence_count"] > 0, "recommendation must carry evidence"

    # every mandatory-compliant finding is grounded with a located quote
    for finding in case["findings"]:
        if finding["requirement_code"] in ("REQ-01", "REQ-02") and finding["status"] == "compliant":
            assert finding["evidence_count"] >= 1
            assert finding["quote"], "mandatory compliance requires a grounded quote"

    # approve → export pack + completion
    decided = await client.post(
        f"/api/v1/approvals/{approval_id}/decisions",
        headers=approver,
        json={"approve": True, "comment": "Nhất trí chọn Thiết bị Việt"},
    )
    assert decided.status_code == 200, decided.text

    run_after = (await client.get(f"/api/v1/runs/{run_id}", headers=member)).json()
    assert run_after["status"] == "completed", run_after
    assert run_after["result"]["export_ref"], "evaluation pack must be exported"
    assert run_after["result"]["memory_written"] is True

    case_after = (await client.get(f"/api/v1/procurement/cases/{case_id}", headers=member)).json()
    assert case_after["status"] == "completed"
    assert case_after["export_ref"].startswith("s3://")

    # the exported pack is a real object in MinIO with the golden content
    from minio import Minio

    urls_env = load_env()
    minio_client = Minio(
        "localhost:9000",
        access_key=urls_env.get("MINIO_ROOT_USER", "dw-minio"),
        secret_key=urls_env.get("MINIO_ROOT_PASSWORD", "change-me-minio"),
        secure=False,
    )
    bucket = urls_env.get("S3_BUCKET_ARTIFACTS", "dw-artifacts")
    key = case_after["export_ref"].replace(f"s3://{bucket}/", "")
    pack = json.loads(minio_client.get_object(bucket, key).read())
    assert pack["recommendation"]["supplier"] == SUPPLIER_A
    assert pack["approval"]["approved"] is True

    # audit chain
    timeline = (await client.get(f"/api/v1/runs/{run_id}/timeline", headers=member)).json()
    actions = [e["action"] for e in timeline]
    for expected in ("run.started", "run.waiting_approval", "run.resumed", "run.completed"):
        assert expected in actions


async def test_scoring_is_deterministic_across_runs(client: httpx.AsyncClient) -> None:
    member = headers("dev|an.nguyen")
    approver = headers("dev|binh.tran")
    totals: list[dict[str, str]] = []
    for _ in range(2):
        case_id, run_id = await _create_and_analyze(client, member)
        case = (await client.get(f"/api/v1/procurement/cases/{case_id}", headers=member)).json()
        totals.append(
            {
                s["supplier_name"]: s["total_score"]
                for s in case["recommendation"]["supplier_scores"]
            }
        )
        approval_id = (await client.get(f"/api/v1/runs/{run_id}", headers=member)).json()[
            "approval_request_id"
        ]
        await client.post(
            f"/api/v1/approvals/{approval_id}/decisions",
            headers=approver,
            json={"approve": False, "comment": "test determinism"},
        )
    assert totals[0] == totals[1], "same inputs must always produce the same scores"


async def test_cross_tenant_case_access_denied(client: httpx.AsyncClient) -> None:
    member_alpha = headers("dev|an.nguyen")
    member_beta = headers("dev|bao.pham", tenant_slug="tenant-beta")
    case_id, _ = await _create_and_analyze(client, member_alpha)
    stolen = await client.get(f"/api/v1/procurement/cases/{case_id}", headers=member_beta)
    assert stolen.status_code == 404
