"""Is this package actually safe to publish?

The gates already answered that question one step at a time, as the case moved.
This answers it about the case as it stands NOW — which is a different
question, because a package keeps changing after a gate has passed. An
addendum bumps the solicitation package; the CP2 approval still refers to the
version the approver read. Publishing then spends an approval on a document
nobody approved.

Everything here is read-only. The findings are advisory except where a rule
pack threshold is violated, and even then nothing moves: a person decides.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.ports import ModelRequest, TracedModelGateway
from dw_kernel.errors import NotFoundError
from dw_kernel.ids import TenantId
from dw_kernel.ports import IdGenerator
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_tender.application.preparation.ports import PreparationUnitOfWorkFactory
from dw_tender.application.preparation.rules import ProcurementRules
from dw_tender.domain.preparation.entities import ArtifactType
from dw_tender.domain.value_objects.ids import PreparationCaseId

Severity = Literal["blocker", "risk", "warning"]

# What each severity costs the score. Blockers dominate on purpose: a package
# with one blocker is not "nearly ready", it is not ready.
_WEIGHT: dict[Severity, int] = {"blocker": 25, "risk": 10, "warning": 4}


@dataclass(frozen=True, slots=True)
class Finding:
    severity: Severity
    code: str
    title: str
    detail: str


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    ready: bool
    score: int
    findings: tuple[Finding, ...]

    def of(self, severity: Severity) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity == severity)


class RedTeamFinding(BaseModel):
    model_config = ConfigDict(extra="ignore")

    severity: Literal["risk", "warning"] = "warning"
    title: str = Field(max_length=160)
    detail: str = Field(max_length=600)


class RedTeamReport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    findings: list[RedTeamFinding] = Field(default_factory=list, max_length=6)


def _items(value: Any) -> list[dict[str, Any]]:
    return [item for item in value or [] if isinstance(item, dict)]


@dataclass
class AssessTenderReadinessHandler:
    """Deterministic checks first; the model only ever adds advisory findings."""

    uow_factory: PreparationUnitOfWorkFactory
    authorization: ScopeAuthorizationService
    rules: ProcurementRules
    id_generator: IdGenerator
    # Without a gateway the deterministic verdict still stands — the red team
    # is a second opinion, never the thing that decides.
    gateway: TracedModelGateway | None = None
    model_profile: str = "balanced"

    async def handle(self, case_id: uuid.UUID, context: AccessContext) -> ReadinessReport:
        await self.authorization.require(
            context=context,
            action="tender.read",
            resource_type="preparation_case",
            resource_id=str(case_id),
        )
        async with self.uow_factory(TenantId(context.tenant_id)) as uow:
            case = await uow.cases.get(PreparationCaseId(case_id))
            if case is None:
                raise NotFoundError("preparation case not found", details={"case_id": str(case_id)})
            artifacts = await uow.artifacts.list_for_case(case.id)

        latest: dict[str, Any] = {}
        for artifact in artifacts:
            current = latest.get(artifact.artifact_type.value)
            if current is None or artifact.artifact_version > current.artifact_version:
                latest[artifact.artifact_type.value] = artifact

        findings: list[Finding] = [
            *self._package_exists(latest),
            *self._package_drift(latest),
            *self._criteria_weights(latest),
            *self._supplier_shortfall(latest, case.estimated_value_minor),
            *self._open_clarifications(latest),
        ]
        findings.extend(await self._red_team(latest, context))

        penalty = sum(_WEIGHT[f.severity] for f in findings)
        score = max(0, 100 - penalty)
        ready = not any(f.severity == "blocker" for f in findings)
        return ReadinessReport(ready=ready, score=score, findings=tuple(findings))

    # ------------------------------------------------------------ checks --
    def _package_exists(self, latest: dict[str, Any]) -> list[Finding]:
        """Finding nothing wrong is not the same as being ready.

        Every other check returns silence when its artifact is absent, so a
        case that has barely started would otherwise score a clean 100.
        """
        if ArtifactType.SOLICITATION_PACKAGE.value in latest:
            return []
        return [
            Finding(
                severity="blocker",
                code="no_package",
                title="Chưa có hồ sơ mời thầu để phát hành",
                detail="Hồ sơ chưa chạy tới bước dựng HSMT, nên chưa có gì để rà soát.",
            )
        ]

    def _package_drift(self, latest: dict[str, Any]) -> list[Finding]:
        """Did anything move after the package was sealed?

        The official manifest records every artifact's version at seal time, so
        the comparison needs nothing but the artifacts themselves.
        """
        manifest = latest.get(ArtifactType.OFFICIAL_PACKAGE_MANIFEST.value)
        if manifest is None:
            return []
        out: list[Finding] = []
        for entry in _items(manifest.content.get("artifacts")):
            kind = str(entry.get("type", ""))
            sealed = int(entry.get("version", 0) or 0)
            current = latest.get(kind)
            if current is None or current.artifact_version <= sealed:
                continue
            out.append(
                Finding(
                    severity="blocker",
                    code="package_drift",
                    title=f"«{kind}» đã đổi sau khi niêm phong",
                    detail=(
                        f"Bản niêm phong dùng v{sealed}, hiện tại đã là "
                        f"v{current.artifact_version}. Phê duyệt đang gắn với v{sealed}, "
                        "không được dùng để phát hành bản mới."
                    ),
                )
            )
        return out

    def _criteria_weights(self, latest: dict[str, Any]) -> list[Finding]:
        criteria = latest.get(ArtifactType.EVALUATION_CRITERIA.value)
        if criteria is None:
            return []
        weighted = _items(criteria.content.get("weighted"))
        total = sum(int(item.get("weight", 0) or 0) for item in weighted)
        required = self.rules.weighted_total_must_equal
        if total == required:
            return []
        return [
            Finding(
                severity="blocker",
                code="criteria_weight",
                title=f"Tổng trọng số tiêu chí là {total}, không phải {required}",
                detail=(
                    "Rule pack yêu cầu tổng trọng số đúng bằng "
                    f"{required}. Chấm điểm trên thang lệch sẽ không so sánh được "
                    "giữa các nhà thầu."
                ),
            )
        ]

    def _supplier_shortfall(self, latest: dict[str, Any], value_minor: int) -> list[Finding]:
        shortlist = latest.get(ArtifactType.SUPPLIER_SHORTLIST.value)
        if shortlist is None:
            return []
        count = len(_items(shortlist.content.get("shortlist")))
        minimum = self.rules.select_method(value_minor).min_suppliers
        if count >= minimum:
            return []
        return [
            Finding(
                severity="blocker",
                code="supplier_shortfall",
                title=f"Mới có {count}/{minimum} nhà cung cấp tối thiểu",
                detail=(
                    "Hình thức mua sắm theo rule pack đòi tối thiểu "
                    f"{minimum} nhà cung cấp cho gói giá trị này."
                ),
            )
        ]

    def _open_clarifications(self, latest: dict[str, Any]) -> list[Finding]:
        listing = latest.get(ArtifactType.CLARIFICATION_LIST.value)
        if listing is None:
            return []
        answered = {
            str(item.get("clarification_id", ""))
            for artifact in (latest.get(ArtifactType.CLARIFICATION_RESPONSE.value),)
            if artifact is not None
            for item in _items(artifact.content.get("answers"))
        }
        open_blocking = [
            item
            for item in _items(listing.content.get("items"))
            if item.get("blocking") and str(item.get("id", "")) not in answered
        ]
        if not open_blocking:
            return []
        return [
            Finding(
                severity="blocker",
                code="open_clarification",
                title=f"Còn {len(open_blocking)} điểm làm rõ bắt buộc chưa trả lời",
                detail="; ".join(str(item.get("question", ""))[:120] for item in open_blocking[:3]),
            )
        ]

    # --------------------------------------------------------- red team --
    async def _red_team(self, latest: dict[str, Any], context: AccessContext) -> list[Finding]:
        package = latest.get(ArtifactType.SOLICITATION_PACKAGE.value)
        criteria = latest.get(ArtifactType.EVALUATION_CRITERIA.value)
        if self.gateway is None or (package is None and criteria is None):
            return []
        sections: list[str] = []
        if package is not None:
            sections.append(f"HỒ SƠ MỜI THẦU:\n{str(package.content)[:4000]}")
        if criteria is not None:
            sections.append(f"TIÊU CHÍ ĐÁNH GIÁ:\n{str(criteria.content)[:2000]}")
        try:
            report = await self.gateway.generate_structured(
                ModelRequest(
                    task="preparation.redteam_solicitation",
                    prompt_id="preparation.redteam_solicitation",
                    prompt_version="1.0.0",
                    variables={"package": "\n\n".join(sections)},
                    model_profile=self.model_profile,
                ),
                RedTeamReport,
                run_context=RunContext(
                    run_id=self.id_generator.new_uuid(),
                    tenant_id=context.tenant_id,
                    workspace_id=context.workspace_id,
                    actor_id=context.principal_id,
                    worker_id="dw01.red_team",
                    worker_version="1.0.0",
                    channel="agent",
                    plan_id=context.plan_id,
                    roles=context.roles,
                    scopes=context.scopes,
                    trace_id="redteam",
                ),
            )
        except Exception:
            # A second opinion that fails to arrive must not look like a clean bill.
            return [
                Finding(
                    severity="warning",
                    code="redteam_unavailable",
                    title="Chưa chạy được rà soát cạnh tranh",
                    detail="Các kiểm tra theo rule pack ở trên vẫn có hiệu lực.",
                )
            ]
        return [
            Finding(
                severity=item.severity,
                code="red_team",
                title=item.title.strip(),
                detail=item.detail.strip(),
            )
            for item in report.findings
            if item.title.strip()
        ]
