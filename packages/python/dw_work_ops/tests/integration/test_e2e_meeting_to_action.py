"""E2E vertical slice: transcript → actions → approval pause → approve →
mock dispatch → external refs + audit timeline. Cross-tenant isolation checked.

Runs the REAL FastAPI app (in-process ASGI) wired by the production composition
root against real Postgres + MinIO, with the deterministic mock model.
"""

from __future__ import annotations

import asyncio
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

DEV_SECRET = "e2e-test-secret-0123456789abcdef"
TRANSCRIPT = (REPO_ROOT / "db" / "fixtures" / "transcripts" / "hop_giao_ban_q3.txt").read_text(
    encoding="utf-8"
)


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
        model_provider="mock",
    )
    container = build_container(settings)
    assert container.work_ops is not None, "work_ops slice must be wired"
    app = create_app(container)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", timeout=60
        ) as http:
            yield http


# Deterministic seed ids (mirror scripts/seed_demo.py::sid)
SEED_NAMESPACE = uuid.UUID("6f0f6f1e-9f6a-4f65-9a1c-000000000d10")


def sid(kind: str, key: str) -> uuid.UUID:
    return uuid.uuid5(SEED_NAMESPACE, f"{kind}:{key}")


def headers(subject: str, tenant_slug: str = "tenant-alpha") -> dict[str, str]:
    from dw_platform.adapters.identity.dev_token import DevTokenVerifier

    token = DevTokenVerifier(DEV_SECRET).issue(subject)
    return {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Id": str(sid("tenant", tenant_slug)),
        "X-Workspace-Id": str(sid("workspace", f"{tenant_slug}:main")),
    }


async def test_meeting_to_action_end_to_end(client: httpx.AsyncClient) -> None:
    member = headers("dev|an.nguyen")
    approver = headers("dev|binh.tran")

    # 1. upload transcript / create meeting
    created = await client.post(
        "/api/v1/work-ops/meetings",
        headers=member,
        json={
            "title": "Họp giao ban tuần — kế hoạch RFQ Q3",
            "occurred_at": "2026-07-20T09:00:00+07:00",
            "transcript_text": TRANSCRIPT,
            "transcript_filename": "hop_giao_ban_q3.txt",
        },
    )
    assert created.status_code == 201, created.text
    meeting_id = created.json()["meeting_id"]

    # 2. generate actions → run pauses at approval
    generated = await client.post(
        f"/api/v1/work-ops/meetings/{meeting_id}/generate-actions", headers=member
    )
    assert generated.status_code == 202, generated.text
    run_id = generated.json()["run_id"]

    run = await client.get(f"/api/v1/runs/{run_id}", headers=member)
    assert run.status_code == 200, run.text
    assert run.json()["status"] == "waiting_approval"
    approval_id = run.json()["approval_request_id"]
    assert approval_id is not None

    # meeting now has draft actions with policy reasons
    meeting = (await client.get(f"/api/v1/work-ops/meetings/{meeting_id}", headers=member)).json()
    assert meeting["status"] == "actions_ready"
    assert meeting["summary"]["headline"].startswith("Họp giao ban")
    # phase 7B: grounded quality analysis persisted alongside the summary
    analysis = meeting["analysis"]
    assert analysis is not None, "meeting analysis must be persisted"
    assert 1 <= analysis["effectiveness_score"] <= 10
    assert len(analysis["went_well"]) >= 1
    assert len(analysis["recommendations"]) >= 1
    for point in analysis["went_well"] + analysis["needs_improvement"]:
        assert point["evidence_quote"], "analysis points must be grounded"
    assert len(meeting["decisions"]) == 2
    assert len(meeting["actions"]) == 2
    titles = {a["title"] for a in meeting["actions"]}
    assert "Soạn hồ sơ RFQ vật tư quý 3" in titles
    binh_action = next(a for a in meeting["actions"] if "RFQ" in a["title"])
    assert binh_action["assignee_display_name"] == "Trần Thị Bình"
    assert binh_action["status"] == "proposed"
    assert "autonomy_a2_requires_review" in binh_action["approval_reasons"]

    # 3. approver sees it in the inbox and approves
    inbox = (await client.get("/api/v1/approvals", headers=approver)).json()
    assert any(item["id"] == approval_id for item in inbox)

    decided = await client.post(
        f"/api/v1/approvals/{approval_id}/decisions",
        headers=approver,
        json={"approve": True, "comment": "Đồng ý giao việc"},
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "approved"

    # 4. run resumed to completion; actions dispatched through the mock connector
    run_after = (await client.get(f"/api/v1/runs/{run_id}", headers=member)).json()
    assert run_after["status"] == "completed", run_after
    dispatch_results = run_after["result"]["dispatch_results"]
    assert all(r["status"] == "dispatched" for r in dispatch_results)

    meeting_after = (
        await client.get(f"/api/v1/work-ops/meetings/{meeting_id}", headers=member)
    ).json()
    assert meeting_after["status"] == "completed"
    for action in meeting_after["actions"]:
        assert action["status"] == "dispatched"
        assert action["external_ref"], "dispatched action must carry the external reference"
        assert action["external_ref"].startswith("MOCK-")

    # memory was written from the closed meeting
    assert run_after["result"]["memory_written"] is True

    # 5. audit timeline covers the whole lifecycle
    timeline = (await client.get(f"/api/v1/runs/{run_id}/timeline", headers=member)).json()
    actions_seen = [event["action"] for event in timeline]
    for expected in (
        "run.started",
        "run.waiting_approval",
        "run.resumed",
        "tool.executed",
        "run.completed",
    ):
        assert expected in actions_seen, f"missing {expected} in {actions_seen}"


async def test_rejected_approval_dispatches_nothing(client: httpx.AsyncClient) -> None:
    member = headers("dev|an.nguyen")
    approver = headers("dev|binh.tran")

    meeting_id = (
        await client.post(
            "/api/v1/work-ops/meetings",
            headers=member,
            json={
                "title": "Họp thử nghiệm reject",
                "occurred_at": "2026-07-21T09:00:00+07:00",
                "transcript_text": TRANSCRIPT,
            },
        )
    ).json()["meeting_id"]
    run_id = (
        await client.post(
            f"/api/v1/work-ops/meetings/{meeting_id}/generate-actions", headers=member
        )
    ).json()["run_id"]
    approval_id = (await client.get(f"/api/v1/runs/{run_id}", headers=member)).json()[
        "approval_request_id"
    ]

    rejected = await client.post(
        f"/api/v1/approvals/{approval_id}/decisions",
        headers=approver,
        json={"approve": False, "comment": "Chưa đủ thông tin"},
    )
    assert rejected.status_code == 200

    meeting_after = (
        await client.get(f"/api/v1/work-ops/meetings/{meeting_id}", headers=member)
    ).json()
    for action in meeting_after["actions"]:
        assert action["status"] == "rejected"
        assert action["external_ref"] is None


async def test_member_cannot_decide_approval(client: httpx.AsyncClient) -> None:
    member = headers("dev|an.nguyen")
    meeting_id = (
        await client.post(
            "/api/v1/work-ops/meetings",
            headers=member,
            json={
                "title": "Họp thử quyền",
                "occurred_at": "2026-07-21T10:00:00+07:00",
                "transcript_text": TRANSCRIPT,
            },
        )
    ).json()["meeting_id"]
    run_id = (
        await client.post(
            f"/api/v1/work-ops/meetings/{meeting_id}/generate-actions", headers=member
        )
    ).json()["run_id"]
    approval_id = (await client.get(f"/api/v1/runs/{run_id}", headers=member)).json()[
        "approval_request_id"
    ]

    # member lacks approvals.decide
    denied = await client.post(
        f"/api/v1/approvals/{approval_id}/decisions",
        headers=member,
        json={"approve": True},
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "permission_denied"


async def test_cross_tenant_meeting_access_denied(client: httpx.AsyncClient) -> None:
    member_alpha = headers("dev|an.nguyen")
    member_beta = headers("dev|bao.pham", tenant_slug="tenant-beta")

    meeting_id = (
        await client.post(
            "/api/v1/work-ops/meetings",
            headers=member_alpha,
            json={
                "title": "Họp nội bộ Alpha",
                "occurred_at": "2026-07-22T09:00:00+07:00",
                "transcript_text": TRANSCRIPT,
            },
        )
    ).json()["meeting_id"]

    stolen = await client.get(f"/api/v1/work-ops/meetings/{meeting_id}", headers=member_beta)
    assert stolen.status_code == 404, "tenant B must not even learn the meeting exists"
