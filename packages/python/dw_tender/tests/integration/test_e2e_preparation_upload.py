"""E2E DW01 upload-only: manual sources, SoD, CP1-CP4 and handoff."""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path
from typing import Any

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

DEV_SECRET = "e2e-preparation-secret-0123456789"
SEED_NAMESPACE = uuid.UUID("6f0f6f1e-9f6a-4f65-9a1c-000000000d10")
PR = """# PR-2026-0042
- Mua 100 laptop
- RAM tối thiểu 16 GB
- Bảo hành (CHƯA RÕ số tháng)
- Địa điểm giao (CHƯA RÕ)
"""


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
def preparation_urls() -> RuntimeUrls:
    resolved = runtime_urls()
    try:
        asyncio.run(recreate_database(resolved.admin))
    except Exception as exc:
        pytest.fail(f"Postgres unreachable — run `make infra-up`. Error: {exc}")
    result = run_migrations(resolved.migrator)
    assert result.returncode == 0, result.stderr
    run_seed(resolved.migrator)
    return resolved


@pytest.fixture
async def preparation_client(preparation_urls: RuntimeUrls):
    from dw_api.bootstrap import build_container
    from dw_api.main import create_app
    from dw_api.settings import ApiSettings

    env = load_env()
    settings = ApiSettings(
        profile="test",
        database_url=preparation_urls.app,
        auth_mode="dev",
        dev_secret=DEV_SECRET,
        s3_endpoint_url=f"http://{preparation_urls.minio_endpoint}",
        s3_access_key=preparation_urls.minio_access_key,
        s3_secret_key=preparation_urls.minio_secret_key,
        s3_bucket=env.get("S3_BUCKET_ARTIFACTS", "dw-artifacts"),
        qdrant_url=preparation_urls.qdrant_url,
        # Never the demo's collection: a dimension change rebuilds it.
        qdrant_collection="dw_knowledge_test",
        model_provider="mock",
    )
    container = build_container(settings)
    assert container.preparation is not None
    app = create_app(container)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", timeout=120
        ) as http:
            yield http


def headers(subject: str) -> dict[str, str]:
    from dw_platform.adapters.identity.dev_token import DevTokenVerifier

    token = DevTokenVerifier(DEV_SECRET).issue(subject)
    return {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Id": str(sid("tenant", "tenant-alpha")),
        "X-Workspace-Id": str(sid("workspace", "tenant-alpha:main")),
    }


async def _case(client: httpx.AsyncClient, case_id: str, actor: dict[str, str]) -> dict[str, Any]:
    response = await client.get(f"/api/v1/procurement/preparation/cases/{case_id}", headers=actor)
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


async def test_dw01_upload_only_cp1_to_cp4(
    preparation_client: httpx.AsyncClient,
) -> None:
    member = headers("dev|an.nguyen")
    # Chi holds both procurement roles, so one account carries every checkpoint.
    # The rule pack still routes CP2 to procurement_head at this value; that the
    # role is REQUIRED, not merely preferred, is covered by the approval_flow
    # unit tests, which need no seeded persona to prove it.
    approver = headers("dev|chi.le")
    created = await preparation_client.post(
        "/api/v1/procurement/preparation/cases/upload",
        headers=member,
        data={
            "title": "Mua 100 laptop",
            "source_pr_ref": "PR-2026-0042",
            "estimated_value_minor": "2500000000",
            "currency": "VND",
            "deadline": "45 ngày",
            "owner_name": "Nguyễn Văn An",
            "supplier_names": "Thiết bị Việt\nMinh Long\nSao Mai",
        },
        files={"file": ("approved-pr.md", PR.encode(), "text/markdown")},
    )
    assert created.status_code == 201, created.text
    case_id = created.json()["case_id"]
    case = await _case(preparation_client, case_id, member)
    assert case["state"] == "draft"
    assert case["documents"][0]["content_hash"]
    assert [item["event_type"] for item in case["notifications"]] == [
        "intake.approval_requested",
        "intake.approval_escalated",
    ]
    assert all(item["status"] == "queued" for item in case["notifications"])

    verified = await preparation_client.post(
        f"/api/v1/procurement/preparation/cases/{case_id}/verify-intake",
        headers=approver,
        json={
            "approval_reference": "APPROVAL-PR-2026-0042",
            "comment": "Đã kiểm tra file và tham chiếu phê duyệt",
        },
    )
    assert verified.status_code == 200, verified.text
    case = await _case(preparation_client, case_id, member)
    # Verification notifies the owner, then auto-starts DW01 — so the approval
    # card is followed by the run's own progress card.
    assert "intake.approved" in [item["event_type"] for item in case["notifications"]]

    first_run = await preparation_client.post(
        f"/api/v1/procurement/preparation/cases/{case_id}/run", headers=member
    )
    assert first_run.status_code == 202, first_run.text
    case = await _case(preparation_client, case_id, member)
    assert case["state"] == "waiting_clarification"
    clarifications = next(
        artifact
        for artifact in reversed(case["artifacts"])
        if artifact["artifact_type"] == "clarification_list"
    )["content"]["items"]
    assert len(clarifications) == 2

    answered = await preparation_client.post(
        f"/api/v1/procurement/preparation/cases/{case_id}/clarifications",
        headers=member,
        json={
            "answers": [
                {
                    "clarification_id": item["id"],
                    "question": item["question"],
                    "answer": "Đã được owner xác nhận",
                    "source_note": "Email owner ngày 25/07/2026",
                }
                for item in clarifications
            ]
        },
    )
    assert answered.status_code == 200, answered.text

    second_run = await preparation_client.post(
        f"/api/v1/procurement/preparation/cases/{case_id}/run", headers=member
    )
    run_id = second_run.json()["run_id"]
    run = (await preparation_client.get(f"/api/v1/runs/{run_id}", headers=member)).json()
    assert run["status"] == "waiting_approval"

    cp1 = await preparation_client.post(
        f"/api/v1/approvals/{run['approval_request_id']}/decisions",
        headers=approver,
        json={"approve": True, "comment": "Đã kiểm tra phương án và evidence CP1"},
    )
    assert cp1.status_code == 200, cp1.text
    run = (await preparation_client.get(f"/api/v1/runs/{run_id}", headers=member)).json()
    assert run["status"] == "waiting_approval"

    cp2 = await preparation_client.post(
        f"/api/v1/approvals/{run['approval_request_id']}/decisions",
        headers=approver,
        json={"approve": True, "comment": "Đã kiểm tra package, criteria và risk CP2"},
    )
    assert cp2.status_code == 200, cp2.text
    case = await _case(preparation_client, case_id, member)
    assert case["state"] == "package_official"

    publication = await preparation_client.post(
        f"/api/v1/procurement/preparation/cases/{case_id}/publication",
        headers=member,
        data={
            "channel": "Email công vụ",
            "recipient_summary": "Ba nhà cung cấp ứng viên",
            "published_at": "2026-07-28T09:00:00+07:00",
            "external_reference": "RFQ-2026-0042-ISSUE-01",
        },
        files={"file": ("receipt.md", b"# publication receipt", "text/markdown")},
    )
    assert publication.status_code == 200, publication.text

    # An addendum changes a package suppliers have already been sent, so it
    # takes the same authority CP3 takes to approve it — not the authority to
    # draft. The requester is refused here even though the case is theirs.
    refused = await preparation_client.post(
        f"/api/v1/procurement/preparation/cases/{case_id}/addendum",
        headers=member,
        data={
            "change_summary": "Gia hạn hai ngày",
            "impact_summary": "Không đổi tiêu chí; áp dụng cho mọi nhà cung cấp",
        },
        files={"file": ("addendum.md", b"# addendum", "text/markdown")},
    )
    assert refused.status_code == 403, refused.text

    addendum = await preparation_client.post(
        f"/api/v1/procurement/preparation/cases/{case_id}/addendum",
        headers=approver,
        data={
            "change_summary": "Gia hạn hai ngày",
            "impact_summary": "Không đổi tiêu chí; áp dụng cho mọi nhà cung cấp",
        },
        files={"file": ("addendum.md", b"# addendum", "text/markdown")},
    )
    assert addendum.status_code == 200, addendum.text
    cp3 = await preparation_client.post(
        f"/api/v1/procurement/preparation/cases/{case_id}/cp3",
        headers=approver,
        json={
            "approve": True,
            "approval_reference": "CP3-2026-0042",
            "comment": "Đã kiểm tra impact",
        },
    )
    assert cp3.status_code == 200, cp3.text

    for supplier in ("Thiết bị Việt", "Minh Long"):
        received = await preparation_client.post(
            f"/api/v1/procurement/preparation/cases/{case_id}/submissions",
            headers=member,
            data={
                "supplier_name": supplier,
                "received_at": "2026-08-12T08:30:00+07:00",
                "receipt_status": "on_time",
                "external_reference": f"RECEIPT-{supplier}",
            },
            files={
                "file": (
                    f"{supplier}.md",
                    f"# Bid {supplier}".encode(),
                    "text/markdown",
                )
            },
        )
        assert received.status_code == 200, received.text

    cp4 = await preparation_client.post(
        f"/api/v1/procurement/preparation/cases/{case_id}/cp4",
        headers=approver,
        data={
            "opening_at": "2026-08-12T09:00:00+07:00",
            "witnesses": "Trần Thị Bình\nNguyễn Văn An",
            "approval_reference": "CP4-2026-0042",
            "comment": "Đủ bằng chứng mở thầu",
        },
        files={"file": ("opening.md", b"# Bid opening minutes", "text/markdown")},
    )
    assert cp4.status_code == 200, cp4.text
    case = await _case(preparation_client, case_id, member)
    assert case["state"] == "completed"
    # The hand-over appends a new version, so read the latest one.
    handoff = max(
        (a for a in case["artifacts"] if a["artifact_type"] == "evaluation_handoff"),
        key=lambda a: a["artifact_version"],
    )
    assert handoff["content"]["submission_count"] == 2
    assert handoff["content"]["handoff_ref"].startswith("s3://")

    # The sealed package crosses to DW02 by itself — nobody re-uploads it.
    evaluation_case_id = handoff["content"]["evaluation_case_id"]
    assert evaluation_case_id, "CP4 must hand the sealed package to evaluation"
    assert handoff["content"]["handed_over_documents"] == 3, "one RFQ + two submissions"
    assert handoff["content"]["unreadable_submissions"] == []

    response = await preparation_client.get(
        f"/api/v1/procurement/cases/{evaluation_case_id}", headers=member
    )
    assert response.status_code == 200, response.text
    evaluation = response.json()
    assert evaluation["title"] == "Mua 100 laptop"
    # Requirements only exist if DW02 actually parsed the RFQ it was handed —
    # this is the seam being proven, not just a row being created.
    assert evaluation["requirements"], "DW02 must read the handed-over package"

    # Confirming CP4 twice must not open a second evaluation of one tender.
    again = await preparation_client.post(
        f"/api/v1/procurement/preparation/cases/{case_id}/cp4",
        headers=approver,
        data={
            "opening_at": "2026-08-12T09:00:00+07:00",
            "witnesses": "Trần Thị Bình",
            "approval_reference": "CP4-2026-0042",
            "comment": "Lặp lại",
        },
        files={"file": ("opening.md", b"# Bid opening minutes", "text/markdown")},
    )
    assert again.status_code in {200, 409}
    case = await _case(preparation_client, case_id, member)
    handoffs = {
        artifact["content"].get("evaluation_case_id")
        for artifact in case["artifacts"]
        if artifact["artifact_type"] == "evaluation_handoff"
        and artifact["content"].get("evaluation_case_id")
    }
    assert handoffs == {evaluation_case_id}

    audit = (
        await preparation_client.get("/api/v1/audit/events?limit=100", headers=approver)
    ).json()
    actions = {event["action"] for event in audit}
    assert {
        "preparation.case.created",
        "preparation.intake.verified",
        "preparation.publication.recorded",
        "preparation.cp4.completed",
    }.issubset(actions)


async def test_rejected_intake_queues_real_requester_notification(
    preparation_client: httpx.AsyncClient,
) -> None:
    member = headers("dev|an.nguyen")
    approver = headers("dev|chi.le")
    created = await preparation_client.post(
        "/api/v1/procurement/preparation/cases/upload",
        headers=member,
        data={
            "title": "Mua thiết bị cần sửa hồ sơ",
            "source_pr_ref": "PR-REJECT-001",
            "estimated_value_minor": "100000000",
            "currency": "VND",
            "deadline": "30 ngày",
            "owner_name": "Nguyễn Văn An",
            "supplier_names": "Nhà cung cấp A",
        },
        files={"file": ("approved-pr.md", PR.encode(), "text/markdown")},
    )
    assert created.status_code == 201, created.text
    case_id = created.json()["case_id"]

    rejected = await preparation_client.post(
        f"/api/v1/procurement/preparation/cases/{case_id}/reject-intake",
        headers=approver,
        json={"comment": "Thiếu chữ ký người có thẩm quyền trên PR"},
    )
    assert rejected.status_code == 200, rejected.text
    case = await _case(preparation_client, case_id, member)
    assert case["state"] == "intake_rejected"
    assert case["notifications"][-1]["event_type"] == "intake.rejected"
    assert case["notifications"][-1]["status"] == "queued"
