"""Dev-only demo endpoints: one-click login + sample data (ADR-013).

Mounted ONLY when auth_mode=dev outside the production profile. The session
endpoint is a convenience token issuer for the seeded roster — authorization
never relies on it: every subsequent request still verifies the token and the
DB membership. The demo-data endpoints require a normal authenticated context.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from dw_api.dependencies.auth import RequireAccessContext
from dw_api.dependencies.services import RequireContainer
from dw_kernel.errors import InfrastructureError, NotFoundError
from dw_platform.adapters.identity.dev_token import DevTokenVerifier


class DemoUser(BaseModel):
    model_config = ConfigDict(frozen=True)

    subject: str
    display_name: str
    description: str
    roles: tuple[str, ...]
    tenant_id: uuid.UUID
    tenant_name: str
    workspace_id: uuid.UUID


class DevSessionRequest(BaseModel):
    subject: str = Field(min_length=1)


class DevSessionResponse(BaseModel):
    token: str
    subject: str
    display_name: str
    roles: tuple[str, ...]
    tenant_id: uuid.UUID
    tenant_name: str
    workspace_id: uuid.UUID
    expires_at: datetime


class DemoCaseResponse(BaseModel):
    case_id: uuid.UUID


class DemoMeetingResponse(BaseModel):
    meeting_id: uuid.UUID


def _load_roster(repo_root: Path) -> list[DemoUser]:
    path = repo_root / "configs" / "demo" / "demo_users.yaml"
    if not path.exists():
        raise InfrastructureError("demo roster missing", details={"path": str(path)})
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [DemoUser.model_validate(entry) for entry in raw["users"]]


def build_dev_router(repo_root: Path, dev_secret: str, include_session: bool = True) -> APIRouter:
    router = APIRouter(prefix="/dev", tags=["dev"])
    fixtures = repo_root / "db" / "fixtures"

    @router.get("/demo-users", response_model=list[DemoUser])
    async def demo_users() -> list[DemoUser]:
        return _load_roster(repo_root)

    if include_session:

        @router.post("/session", response_model=DevSessionResponse)
        async def create_session(request: DevSessionRequest) -> DevSessionResponse:
            roster = {user.subject: user for user in _load_roster(repo_root)}
            user = roster.get(request.subject)
            if user is None:
                raise NotFoundError("unknown demo subject", details={"subject": request.subject})
            ttl = timedelta(hours=8)
            token = DevTokenVerifier(dev_secret).issue(user.subject, ttl=ttl)
            return DevSessionResponse(
                token=token,
                subject=user.subject,
                display_name=user.display_name,
                roles=user.roles,
                tenant_id=user.tenant_id,
                tenant_name=user.tenant_name,
                workspace_id=user.workspace_id,
                expires_at=datetime.now(tz=UTC) + ttl,
            )

    @router.post("/demo/tender-case", response_model=DemoCaseResponse, status_code=201)
    async def create_demo_tender_case(
        context: RequireAccessContext, container: RequireContainer
    ) -> DemoCaseResponse:
        """Create a sample tender case from the bundled fixtures (normal authz)."""
        if container.tender is None:
            raise InfrastructureError("tender slice is not configured")
        from dw_tender.application.handlers import CreateTenderCaseCommand, DocumentUpload
        from dw_tender.domain.entities import DocumentKind

        tender_dir = fixtures / "tender"
        command = CreateTenderCaseCommand(
            title="Demo — RFQ vật tư sản xuất quý 3/2026",
            description="Hồ sơ mẫu tạo từ nút demo (fixtures đóng gói sẵn)",
            documents=(
                DocumentUpload(
                    kind=DocumentKind.RFQ,
                    title="RFQ vật tư Q3",
                    content=(tender_dir / "rfq_vat_tu_q3.txt").read_text(encoding="utf-8"),
                ),
                DocumentUpload(
                    kind=DocumentKind.SUPPLIER_SUBMISSION,
                    title="Chào giá Thiết bị Việt",
                    content=(tender_dir / "chao_gia_thiet_bi_viet.txt").read_text(encoding="utf-8"),
                    supplier_name="Công ty TNHH Thiết bị Việt",
                ),
                DocumentUpload(
                    kind=DocumentKind.SUPPLIER_SUBMISSION,
                    title="Chào giá Vật tư Miền Nam",
                    content=(tender_dir / "chao_gia_vat_tu_mien_nam.txt").read_text(
                        encoding="utf-8"
                    ),
                    supplier_name="Công ty CP Vật tư Miền Nam",
                ),
            ),
        )
        case_id = await container.tender.create_case.handle(command, context)
        return DemoCaseResponse(case_id=case_id)

    @router.post("/demo/meeting", response_model=DemoMeetingResponse, status_code=201)
    async def create_demo_meeting(
        context: RequireAccessContext, container: RequireContainer
    ) -> DemoMeetingResponse:
        """Create a sample meeting from the bundled transcript (normal authz)."""
        if container.work_ops is None:
            raise InfrastructureError("work_ops slice is not configured")
        from dw_work_ops.application.handlers import CreateMeetingCommand

        transcript = (fixtures / "transcripts" / "hop_giao_ban_q3.txt").read_text(encoding="utf-8")
        command = CreateMeetingCommand(
            title="Demo — Họp giao ban quý 3",
            occurred_at=datetime.now(tz=UTC),
            transcript_text=transcript,
            transcript_filename="hop_giao_ban_q3.txt",
        )
        meeting_id = await container.work_ops.create_meeting.handle(command, context)
        return DemoMeetingResponse(meeting_id=meeting_id)

    return router
