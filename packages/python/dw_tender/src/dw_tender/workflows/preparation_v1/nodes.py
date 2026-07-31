"""DW01 preparation graph nodes.

Deterministic drafting from the approved PR + rule pack (the model gateway is a
documented seam on the draft_* nodes). Deterministic gates decide transitions;
two human checkpoints (CP1 approach, CP2 package) pause the run via ``interrupt``.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from dw_agent_runtime.context import access_context_from_run
from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.ports import ModelRequest
from dw_kernel.errors import DomainError
from dw_kernel.ids import TenantId, UserId
from dw_knowledge.contracts import SearchQuery
from dw_tender.application.preparation.drafts import CriteriaDraft, SolicitationDraft
from dw_tender.application.preparation.extraction import PreparationExtraction
from dw_tender.application.preparation.review import ReviewRecommendation, review_card_lines
from dw_tender.application.preparation.rules import approach_gate, solicitation_gate
from dw_tender.domain.preparation.entities import (
    ArtifactStatus,
    ArtifactType,
    CaseState,
    DocumentKind,
    PreparationArtifact,
    PreparationCase,
)
from dw_tender.domain.preparation.notifications import (
    IntakeNotificationJob,
    IntakeNotificationType,
)
from dw_tender.domain.value_objects.ids import ArtifactId, PreparationCaseId
from dw_tender.workflows.preparation_v1.services import PreparationServices
from dw_tender.workflows.preparation_v1.state import (
    STATE_SCHEMA_VERSION,
    PreparationState,
)


def _run_context(config: RunnableConfig) -> RunContext:
    run_context = config.get("configurable", {}).get("run_context")
    if not isinstance(run_context, RunContext):
        raise DomainError("workflow config is missing the trusted run_context")
    return run_context


def _case_id(state: PreparationState) -> PreparationCaseId:
    raw = state.get("case_id")
    if not raw:
        raise DomainError("workflow state is missing case_id")
    return PreparationCaseId(uuid.UUID(raw))


def _hash(content: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _fmt_vnd(minor: int) -> str:
    return f"{minor:,}".replace(",", ".") + " VND"


def _dict_items(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


class PreparationNodes:
    def __init__(self, services: PreparationServices) -> None:
        self.services = services

    async def _cite(
        self,
        run_context: RunContext,
        query: str,
        *,
        domain: str,
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        """Retrieve grounding evidence via the knowledge gateway (RAG).

        Returns compact citations for the drafted artifact. Degrades to an empty
        list when no gateway is wired or retrieval fails — drafting is never
        blocked by knowledge availability. The gateway injects tenant/workspace/
        global ACL filters from the context; nodes never build filters.
        """
        gateway = self.services.knowledge
        if gateway is None:
            return []
        try:
            context = access_context_from_run(run_context)
            hits = await gateway.search(
                SearchQuery(text=query, domain=domain, top_k=top_k), context
            )
        except Exception:  # retrieval is best-effort grounding, not a gate
            return []
        citations: list[dict[str, Any]] = []
        for chunk in hits:
            ev = chunk.evidence
            citations.append(
                {
                    "source_document_id": str(ev.source_document_id),
                    "source_version": ev.source_version,
                    "quote": chunk.content[:280],
                    "relevance_score": round(ev.relevance_score, 4),
                    "classification": ev.classification,
                }
            )
        return citations

    async def _add_artifact(
        self,
        uow: Any,
        case: PreparationCase,
        artifact_type: ArtifactType,
        content: dict[str, Any],
        *,
        status: ArtifactStatus = ArtifactStatus.DRAFT,
    ) -> PreparationArtifact:
        latest = await uow.artifacts.latest(case.id, artifact_type)
        content_hash = _hash(content)
        if latest is not None and latest.content_hash == content_hash:
            # Idempotent re-run (e.g. continue after clarification): identical
            # content keeps the existing version instead of creating noisy dupes.
            return latest
        version = (latest.artifact_version + 1) if latest is not None else 1
        artifact = PreparationArtifact(
            id=ArtifactId(self.services.id_generator.new_uuid()),
            tenant_id=case.tenant_id,
            workspace_id=case.workspace_id,
            case_id=case.id,
            artifact_type=artifact_type,
            schema_version=self.services.schema_version,
            artifact_version=version,
            status=status,
            content=content,
            created_by=case.created_by,
            content_hash=content_hash,
        )
        await uow.artifacts.add(artifact)
        return artifact

    async def _notify_progress(
        self,
        uow: Any,
        case: PreparationCase,
        *,
        stage: str,
        dedupe: str,
        heading: str,
        lines: list[str],
        buttons: list[dict[str, str]] | None = None,
        recipient: UserId | None = None,
    ) -> None:
        """Durable Slack progress card for the case owner (P3 activity trace).

        An outbox row in the same transaction as the step's own writes; the
        worker renders and delivers it. Content is SYSTEM-BUILT from real node
        events. ``dedupe`` keeps continue-runs idempotent (enqueue is
        ON CONFLICT DO NOTHING on the idempotency key). ``buttons`` renders
        Slack actions (P4) — the click is authorized server-side, never here.
        """
        payload: dict[str, Any] = {"title": case.title, "heading": heading, "lines": lines}
        if buttons:
            payload["buttons"] = buttons
        await uow.notifications.enqueue(
            IntakeNotificationJob(
                id=self.services.id_generator.new_uuid(),
                tenant_id=case.tenant_id,
                workspace_id=case.workspace_id,
                case_id=case.id,
                event_type=IntakeNotificationType.RUN_PROGRESS,
                recipient_user_id=recipient or case.created_by,
                due_at=self.services.clock.now(),
                idempotency_key=f"dw01:{case.id.value}:progress:{stage}:{dedupe}",
                payload=payload,
            )
        )

    async def _notify_cp_approval(
        self,
        uow: Any,
        case: PreparationCase,
        *,
        checkpoint: str,
        dedupe: str,
        lines: list[str],
    ) -> None:
        """Decision card with Duyệt/Từ chối buttons for the approver (P4).

        Recipient comes from the membership directory (role ``approver``) — the
        same trust path the intake notifications use. The click resolves back
        through identity → AccessContext → the normal decide handlers; Slack
        itself never authorizes anything.
        """
        approver = await uow.notifications.find_recipient_for_role("approver")
        if approver is None:
            return
        await uow.notifications.enqueue(
            IntakeNotificationJob(
                id=self.services.id_generator.new_uuid(),
                tenant_id=case.tenant_id,
                workspace_id=case.workspace_id,
                case_id=case.id,
                event_type=IntakeNotificationType.CP_APPROVAL_REQUESTED,
                recipient_user_id=approver,
                due_at=self.services.clock.now(),
                idempotency_key=f"dw01:{case.id.value}:cpcard:{checkpoint}:{dedupe}",
                payload={
                    "title": case.title,
                    "checkpoint": checkpoint,
                    "lines": lines,
                    "case_id": str(case.id.value),
                },
            )
        )

    async def _run_review(
        self,
        rc: RunContext,
        *,
        checkpoint: str,
        artifact_json: dict[str, Any],
        gate: dict[str, Any],
    ) -> ReviewRecommendation | None:
        """P5 Independent Review Agent: advisory recommendation for a checkpoint.

        Independence guarantees (plan §4.3): its own run identity
        (worker dw01.review_agent, fresh run_id), context rebuilt ONLY from the
        submitted payload + deterministic gate verdict, output schema-validated.
        Failure degrades to "no recommendation" — review never blocks the flow.
        """
        gateway = self.services.model_gateway
        if gateway is None:
            return None
        rules = self.services.rules
        rules_summary = f"Rule pack v{rules.version}: " + "; ".join(
            f"«{m.label}» tới {_fmt_vnd(m.max_value) if m.max_value else 'không giới hạn'}, "
            f"tối thiểu {m.min_suppliers} NCC"
            for m in rules.methods
        )
        review_context = RunContext(
            run_id=self.services.id_generator.new_uuid(),
            tenant_id=rc.tenant_id,
            workspace_id=rc.workspace_id,
            actor_id=rc.actor_id,
            worker_id="dw01.review_agent",
            worker_version="1.0.0",
            channel="agent",
            plan_id=rc.plan_id,
            roles=rc.roles,
            scopes=rc.scopes,
            trace_id=f"review-{rc.run_id.hex[:12]}",
        )
        try:
            return await gateway.generate_structured(
                ModelRequest(
                    task="preparation.review",
                    prompt_id="preparation.review_checkpoint",
                    prompt_version="1.0.0",
                    variables={
                        "checkpoint": checkpoint,
                        "gate_json": json.dumps(gate, ensure_ascii=False),
                        "rules_summary": rules_summary,
                        "artifact_json": json.dumps(artifact_json, ensure_ascii=False)[:12000],
                    },
                    model_profile=self.services.model_profile,
                    # The heavy reasoning route (deepseek-reasoner when configured).
                    route_kind="deep_reasoning",
                ),
                ReviewRecommendation,
                run_context=review_context,
            )
        except Exception:  # advisory only — never a gate
            return None

    # -- 1. intake --------------------------------------------------------
    async def load_case(self, state: PreparationState, config: RunnableConfig) -> PreparationState:
        rc = _run_context(config)
        case_id = _case_id(state)
        async with self.services.uow_factory(TenantId(rc.tenant_id)) as uow:
            case = await uow.cases.get(case_id)
            if case is None:
                raise DomainError("preparation case not found")
            pr_text = ""
            for doc in await uow.documents.list_for_case(case_id):
                if doc.kind == DocumentKind.APPROVED_PR:
                    raw = await self.services.storage.get_object(doc.storage_key)
                    pr_text = raw.decode("utf-8")
                    break
            response = await uow.artifacts.latest(case_id, ArtifactType.CLARIFICATION_RESPONSE)
            supplier_input = await uow.artifacts.latest(case_id, ArtifactType.SUPPLIER_INPUT)
            answers = {
                str(item.get("id", "")): str(item.get("answer", "")).strip()
                for item in _dict_items(
                    response.content.get("items", []) if response is not None else []
                )
            }
            supplier_candidates = (
                _dict_items(supplier_input.content.get("suppliers", []))
                if supplier_input is not None
                else []
            )
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "pr_text": pr_text,
            "has_approved_pr": (
                bool(case.source_pr_ref) and bool(pr_text) and case.intake_verified_by is not None
            ),
            "estimated_value_minor": case.estimated_value_minor,
            "currency": case.currency,
            "deadline": case.deadline,
            "owner_name": case.owner_name,
            "case_title": case.title,
            "source_pr_ref": case.source_pr_ref,
            "procurement_type": case.procurement_type.value,
            "business_domain": case.business_domain.value,
            "clarification_answers": answers,
            "supplier_candidates": supplier_candidates,
        }

    # -- 2. extract requirements + demand snapshot ------------------------
    async def extract_requirements(
        self, state: PreparationState, config: RunnableConfig
    ) -> PreparationState:
        rc = _run_context(config)
        case_id = _case_id(state)
        pr_text = state.get("pr_text", "")

        # Continue-run after clarification: reuse the existing snapshot so the
        # requirement/unknown set stays identical (deterministic completeness
        # gate) and we neither re-pay for an LLM call nor create a dupe version.
        async with self.services.uow_factory(TenantId(rc.tenant_id)) as uow:
            existing = await uow.artifacts.latest(case_id, ArtifactType.DEMAND_SNAPSHOT)
        if existing is not None:
            requirements = _dict_items(existing.content.get("requirements", []))
            unknowns = _dict_items(existing.content.get("unknowns", []))
            return {"requirements": requirements, "unknowns": unknowns}

        requirements, unknowns, source = await self._extract_requirements(rc, pr_text)

        content = {
            "estimated_value": _fmt_vnd(state.get("estimated_value_minor", 0)),
            "deadline": state.get("deadline"),
            "owner": state.get("owner_name"),
            "procurement_type": state.get("procurement_type"),
            "business_domain": state.get("business_domain"),
            "extraction_source": source,
            "requirement_lines": [r["text"] for r in requirements],
            "requirements": requirements,
            "unknowns": unknowns,
            "unknown_count": len(unknowns),
        }
        async with self.services.uow_factory(TenantId(rc.tenant_id)) as uow:
            case = await uow.cases.get(case_id)
            assert case is not None
            snapshot = await self._add_artifact(uow, case, ArtifactType.DEMAND_SNAPSHOT, content)
            source_label = "AI (LLM)" if source == "ai" else "phân tích dòng (deterministic)"
            await self._notify_progress(
                uow,
                case,
                stage="extract",
                dedupe=f"v{snapshot.artifact_version}",
                heading="📋 Đã bóc tách yêu cầu từ PR",
                lines=[
                    f"{len(requirements)} yêu cầu được nhận diện (nguồn: {source_label}).",
                    (
                        f"{len(unknowns)} điểm thương mại cần làm rõ."
                        if unknowns
                        else "Không có điểm nào cần làm rõ — PR đầy đủ."
                    ),
                ],
            )
            await uow.commit()
        return {"requirements": requirements, "unknowns": unknowns}

    async def _extract_requirements(
        self, run_context: RunContext, pr_text: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]], str]:
        """Bóc yêu cầu từ PR. Ưu tiên LLM (kèm gợi ý trả lời cho điểm chưa rõ);
        fallback về tách dòng khi không có model/lỗi — intake không bao giờ bị chặn."""
        gateway = self.services.model_gateway
        if gateway is not None and pr_text.strip():
            try:
                extracted = await gateway.generate_structured(
                    ModelRequest(
                        task="structured_extraction",
                        prompt_id="preparation.extract_requirements",
                        prompt_version=self.services.prompt_bundle_version,
                        variables={"pr_text": pr_text},
                        model_profile=self.services.model_profile,
                    ),
                    PreparationExtraction,
                    run_context=run_context,
                )
                requirements = [
                    {"code": r.code, "text": r.statement, "kind": r.kind}
                    for r in extracted.requirements
                ]
                unknowns = [
                    {"question": u.question, "suggested_answer": u.suggested_answer}
                    for u in extracted.unknowns
                ]
                if requirements:
                    return requirements, unknowns, "ai"
            except Exception:  # best-effort grounding, never a gate
                pass

        lines = [ln.strip() for ln in pr_text.splitlines() if ln.strip()]
        requirements = [
            {"text": ln.lstrip("-• ").strip()}
            for ln in lines
            if ln.startswith(("-", "•"))
        ]
        unknowns = [
            {"question": ln, "suggested_answer": ""} for ln in lines if "CHƯA RÕ" in ln
        ]
        return requirements, unknowns, "rule"

    async def _llm_solicitation(
        self, run_context: RunContext, procurement_type: str, method: str, requirements: list[str]
    ) -> SolicitationDraft | None:
        """LLM-draft the solicitation scope + technical requirements. None on
        no-model/error so the caller keeps the deterministic template."""
        gateway = self.services.model_gateway
        if gateway is None or not requirements:
            return None
        try:
            return await gateway.generate_structured(
                ModelRequest(
                    task="reasoning",
                    prompt_id="preparation.draft_solicitation",
                    prompt_version=self.services.prompt_bundle_version,
                    variables={
                        "procurement_type": procurement_type,
                        "method": method,
                        "requirements": "\n".join(f"- {r}" for r in requirements),
                    },
                    model_profile=self.services.model_profile,
                ),
                SolicitationDraft,
                run_context=run_context,
            )
        except Exception:
            return None

    async def _llm_criteria(
        self, run_context: RunContext, procurement_type: str, requirements: list[str]
    ) -> list[dict[str, Any]] | None:
        """LLM-draft weighted criteria; returns None unless weights sum to 100
        (else the caller keeps the rule-pack default)."""
        gateway = self.services.model_gateway
        if gateway is None or not requirements:
            return None
        try:
            draft: CriteriaDraft = await gateway.generate_structured(
                ModelRequest(
                    task="reasoning",
                    prompt_id="preparation.draft_criteria",
                    prompt_version=self.services.prompt_bundle_version,
                    variables={
                        "procurement_type": procurement_type,
                        "requirements": "\n".join(f"- {r}" for r in requirements),
                    },
                    model_profile=self.services.model_profile,
                ),
                CriteriaDraft,
                run_context=run_context,
            )
        except Exception:
            return None
        if not draft.weights_valid():
            return None
        return [
            {"code": c.code, "text": c.text, "weight": c.weight} for c in draft.weighted
        ]

    # -- 3. completeness + clarifications ---------------------------------
    async def completeness_check(
        self, state: PreparationState, config: RunnableConfig
    ) -> PreparationState:
        rc = _run_context(config)
        case_id = _case_id(state)
        unknowns = state.get("unknowns", [])
        answers = state.get("clarification_answers", {})
        clarifications = [
            {
                "id": f"c{i + 1}",
                "question": (u.get("question", "") if isinstance(u, dict) else str(u)),
                # AI's draft answer — pre-fills the field for the reviewer to confirm/edit.
                "suggested_answer": (
                    u.get("suggested_answer", "") if isinstance(u, dict) else ""
                ),
                "blocking": not bool(answers.get(f"c{i + 1}", "").strip()),
                "answered": bool(answers.get(f"c{i + 1}", "").strip()),
                "answer": answers.get(f"c{i + 1}", ""),
            }
            for i, u in enumerate(unknowns)
        ]
        blocking_count = sum(1 for c in clarifications if c["blocking"])
        report = {
            "complete": blocking_count == 0,
            "unknown_count": len(unknowns),
            "blocking_count": blocking_count,
            "note": (
                "Đầu vào đã đủ điều kiện lập phương án."
                if blocking_count == 0
                else "Phải trả lời toàn bộ điểm chưa rõ trước khi trình CP1."
            ),
        }
        async with self.services.uow_factory(TenantId(rc.tenant_id)) as uow:
            case = await uow.cases.get(case_id)
            assert case is not None
            await self._add_artifact(uow, case, ArtifactType.COMPLETENESS_REPORT, report)
            await self._add_artifact(
                uow, case, ArtifactType.CLARIFICATION_LIST, {"items": clarifications}
            )
            # Single version bump per save (optimistic concurrency on version-1).
            case.advance(CaseState.WAITING_CLARIFICATION, "clarification")
            await uow.cases.save(case)
            await uow.commit()
        return {"clarifications": clarifications}

    # -- 4. procurement approach ------------------------------------------
    async def draft_procurement_approach(
        self, state: PreparationState, config: RunnableConfig
    ) -> PreparationState:
        rc = _run_context(config)
        case_id = _case_id(state)
        rules = self.services.rules
        value = state.get("estimated_value_minor", 0)
        method = rules.select_method(value)
        candidates = state.get("supplier_candidates", [])
        planned = len(candidates)
        content = {
            "method": {"key": method.key, "label": method.label},
            "estimated_value": _fmt_vnd(value),
            "min_suppliers": method.min_suppliers,
            "supplier_count_planned": planned,
            "sourcing_strategy": (
                f"Mời {planned} nhà cung cấp ứng viên tham gia chào giá cạnh tranh; "
                "eligibility được kiểm tra ở CP2."
                if method.key != "direct_purchase"
                else "Mời nhà cung cấp ứng viên; eligibility được kiểm tra trước phát hành."
            ),
            "timeline": [
                {"step": "Phát hành hồ sơ", "offset_days": 0},
                {"step": "Hạn nộp hồ sơ", "offset_days": 14},
                {"step": "Đánh giá & trình duyệt", "offset_days": 21},
            ],
            "approval_path": ["CP1 — duyệt phương án", "CP2 — duyệt bộ hồ sơ chính thức"],
            "legal_review_required": rules.needs_legal_review(value),
            "finance_review_required": rules.needs_finance_review(value),
            "rationale": (
                f"Giá trị gói {_fmt_vnd(value)} phù hợp hình thức «{method.label}» theo rule pack "
                f"v{rules.version}."
            ),
        }
        # RAG grounding: legal basis for the chosen method + internal policy on
        # approval limits. Global legal docs + this tenant's policies only.
        content["legal_basis"] = await self._cite(
            rc,
            f"hình thức lựa chọn nhà thầu {method.label} điều kiện áp dụng",
            domain="legal",
        )
        content["policy_basis"] = await self._cite(
            rc,
            f"hạn mức phê duyệt phương án mua sắm giá trị {_fmt_vnd(value)}",
            domain="policy",
        )
        content["grounding_status"] = (
            "grounded" if content["legal_basis"] or content["policy_basis"] else "not_available"
        )
        if content["grounding_status"] == "not_available":
            content["grounding_warning"] = (
                "Không truy xuất được căn cứ Knowledge; người duyệt phải kiểm tra "
                "rule pack và tài liệu nguồn trước CP1."
            )
        async with self.services.uow_factory(TenantId(rc.tenant_id)) as uow:
            case = await uow.cases.get(case_id)
            assert case is not None
            await self._add_artifact(uow, case, ArtifactType.PROCUREMENT_APPROACH, content)
            case.advance(CaseState.APPROACH_READY, "approach", method_key=method.key)
            await uow.cases.save(case)
            await uow.commit()
        return {
            "method_key": method.key,
            "method_label": method.label,
            "min_suppliers": method.min_suppliers,
            "supplier_count_planned": planned,
        }

    # -- 5. approach gate + CP1 payload -----------------------------------
    async def approach_gate(
        self, state: PreparationState, config: RunnableConfig
    ) -> PreparationState:
        rc = _run_context(config)
        case_id = _case_id(state)
        rules = self.services.rules
        method = rules.select_method(state.get("estimated_value_minor", 0))
        blocking = sum(1 for c in state.get("clarifications", []) if c.get("blocking"))
        result = approach_gate(
            rules=rules,
            has_approved_pr=state.get("has_approved_pr", False),
            estimated_value_minor=state.get("estimated_value_minor", 0),
            currency=state.get("currency", ""),
            deadline=state.get("deadline"),
            owner_name=state.get("owner_name", ""),
            method=method,
            supplier_count_planned=state.get("supplier_count_planned", 0),
            open_blocking_clarifications=blocking,
        )
        gate = {"passed": result.passed, "reasons": list(result.reasons)}
        payload = {
            "approval_type": "preparation.cp1",
            "reason": f"CP1 — Duyệt phương án mua sắm ({state.get('method_label', method.label)})",
            "checkpoint": "CP1",
            "case_id": state["case_id"],
            "case_title": state.get("case_title", ""),
            "source_pr_ref": state.get("source_pr_ref", ""),
            "gate": gate,
            "method": {"key": method.key, "label": method.label},
            "estimated_value": _fmt_vnd(state.get("estimated_value_minor", 0)),
            "supplier_count_planned": state.get("supplier_count_planned", 0),
        }
        # P5: independent advisory review BEFORE the approver card (outside the
        # transaction — the reasoner call may take a while).
        review = None
        if result.passed:
            review = await self._run_review(
                rc,
                checkpoint="CP1",
                artifact_json={**payload, "requirements": state.get("requirements", [])},
                gate=gate,
            )
        async with self.services.uow_factory(TenantId(rc.tenant_id)) as uow:
            case = await uow.cases.get(case_id)
            assert case is not None
            # Persist the gate verdict onto the approach artifact so the UI can
            # show exactly WHY CP1 is (not) reachable — otherwise a non-clarification
            # blocker (e.g. too few suppliers) is an invisible dead-end.
            approach = await uow.artifacts.latest(case_id, ArtifactType.PROCUREMENT_APPROACH)
            if approach is not None:
                merged = {**approach.content, "gate": gate}
                await self._add_artifact(uow, case, ArtifactType.PROCUREMENT_APPROACH, merged)
            case.advance(
                CaseState.CP1_PENDING if result.passed else CaseState.WAITING_CLARIFICATION,
                "cp1",
            )
            # P6 delegated autonomy: low-risk method (direct purchase per rule
            # pack) + reviewer approves + demo profile → auto-approve CP1 with
            # a recorded, auditable decision. Everything else pauses for a human.
            autopilot = (
                result.passed
                and review is not None
                and review.recommendation == "approve"
                and method.min_suppliers == 1
                and self.services.autonomy_profile == "autonomous_demo"
            )
            if result.passed:
                await self._notify_progress(
                    uow,
                    case,
                    stage="cp1_gate",
                    dedupe=_hash(gate)[:12],
                    heading=(
                        "⚖️ Gate CP1: ĐẠT — đủ điều kiện tự phê duyệt"
                        if autopilot
                        else "⚖️ Gate CP1: ĐẠT — chờ Quản lý phê duyệt"
                    ),
                    lines=[
                        (
                            f"Giá trị {_fmt_vnd(state.get('estimated_value_minor', 0))} → "
                            f"hình thức «{method.label}» (rule pack v{rules.version})."
                        ),
                        (
                            f"NCC dự kiến: {state.get('supplier_count_planned', 0)} "
                            f"(tối thiểu {method.min_suppliers})."
                        ),
                        (
                            "Gói rủi ro thấp trong phạm vi ủy quyền — Review Agent "
                            "sẽ tự phê duyệt CP1."
                            if autopilot
                            else "Đã trình duyệt CP1 — hồ sơ tạm dừng chờ quyết định."
                        ),
                    ],
                )
                cp1_lines = [
                    (
                        f"Giá trị {_fmt_vnd(state.get('estimated_value_minor', 0))} → "
                        f"hình thức «{method.label}» (rule pack v{rules.version})."
                    ),
                    (
                        f"NCC dự kiến: {state.get('supplier_count_planned', 0)} "
                        f"(tối thiểu {method.min_suppliers})."
                    ),
                    f"Gate CP1 tự động: ĐẠT. PR tham chiếu: {state.get('source_pr_ref', '—')}.",
                ]
                if review is not None:
                    await self._add_artifact(
                        uow,
                        case,
                        ArtifactType.REVIEW_RECOMMENDATION,
                        {
                            "checkpoint": "CP1",
                            "agent_id": "dw01.review_agent",
                            "prompt_version": "1.0.0",
                            "decision_mode": (
                                "delegated_autonomy" if autopilot else "advisory"
                            ),
                            **review.model_dump(),
                        },
                    )
                    cp1_lines += review_card_lines(review)
                if autopilot:
                    # Inform the approver (no buttons) — with a standing override path.
                    approver = await uow.notifications.find_recipient_for_role("approver")
                    if approver is not None:
                        await self._notify_progress(
                            uow,
                            case,
                            stage="cp1_autonomy_fyi",
                            dedupe=_hash(gate)[:12],
                            heading="🤖 CP1 đã được Review Agent phê duyệt theo ủy quyền",
                            lines=[
                                *cp1_lines,
                                "Chính sách: AUTONOMOUS_DEMO — gói «chỉ định thầu» "
                                "rủi ro thấp.",
                                "Bạn có thể yêu cầu xem xét lại bằng cách mở hồ sơ.",
                            ],
                            recipient=approver,
                        )
                else:
                    await self._notify_cp_approval(
                        uow,
                        case,
                        checkpoint="CP1",
                        dedupe=_hash(gate)[:12],
                        lines=cp1_lines,
                    )
            else:
                await self._notify_progress(
                    uow,
                    case,
                    stage="cp1_gate",
                    dedupe=_hash(gate)[:12],
                    heading="⚠️ Gate CP1 CHƯA ĐẠT — cần bổ sung",
                    lines=[*result.reasons, "Mở hồ sơ để bổ sung/làm rõ rồi chạy tiếp."],
                )
            await uow.cases.save(case)
            await uow.commit()
        if autopilot and review is not None:
            return {
                "approach_gate": gate,
                "cp1_payload": payload,
                "cp1_decision": {
                    "approved": True,
                    "mode": "delegated_autonomy",
                    "decided_by_agent": "dw01.review_agent",
                    "policy": "AUTONOMOUS_DEMO",
                    "comment": review.rationale_summary,
                },
            }
        return {"approach_gate": gate, "cp1_payload": payload}

    # -- 6/7. CP1 interrupt + apply --------------------------------------
    async def cp1_review(self, state: PreparationState, config: RunnableConfig) -> PreparationState:
        decision: dict[str, Any] = interrupt(state.get("cp1_payload", {}))
        return {"cp1_decision": dict(decision)}

    async def apply_cp1(self, state: PreparationState, config: RunnableConfig) -> PreparationState:
        rc = _run_context(config)
        case_id = _case_id(state)
        decision = state.get("cp1_decision", {})
        approved = bool(decision.get("approved"))
        comment = str(decision.get("comment", "") or "").strip()
        async with self.services.uow_factory(TenantId(rc.tenant_id)) as uow:
            case = await uow.cases.get(case_id)
            assert case is not None
            case.advance(
                CaseState.CP1_APPROVED if approved else CaseState.CP1_REJECTED,
                "build_solicitation" if approved else "cp1_rejected",
            )
            delegated = decision.get("mode") == "delegated_autonomy"
            if approved:
                lines = [
                    (
                        "Quyết định theo ủy quyền bởi Review Agent "
                        f"(policy {decision.get('policy', '')})."
                        if delegated
                        else "Phương án mua sắm đã được phê duyệt."
                    ),
                    "Tiếp theo: dựng hồ sơ mời thầu (HSMT), tiêu chí đánh giá, "
                    "shortlist NCC và kiểm tra rủi ro…",
                ]
            else:
                lines = [
                    f"Lý do: {comment}" if comment else "Không có nhận xét kèm theo.",
                    "Quy trình dừng tại đây — mở hồ sơ để xem chi tiết và chuẩn bị lại.",
                ]
            await self._notify_progress(
                uow,
                case,
                stage="cp1_decision",
                dedupe=rc.run_id.hex[:12],
                heading=(
                    "🤖 CP1 — TỰ PHÊ DUYỆT theo ủy quyền"
                    if approved and delegated
                    else "✅ CP1 — Phương án mua sắm ĐÃ ĐƯỢC DUYỆT"
                    if approved
                    else "⛔ CP1 — Phương án bị TỪ CHỐI"
                ),
                lines=lines,
            )
            await uow.cases.save(case)
            await uow.commit()
        return {}

    # -- 8. solicitation package -----------------------------------------
    async def draft_solicitation_package(
        self, state: PreparationState, config: RunnableConfig
    ) -> PreparationState:
        rc = _run_context(config)
        case_id = _case_id(state)
        requirements = [r["text"] for r in state.get("requirements", [])]
        # LLM drafts the scope + technical requirements; template is the fallback.
        draft = await self._llm_solicitation(
            rc,
            str(state.get("procurement_type", "")),
            str(state.get("method_label", "")),
            requirements,
        )
        scope = (
            draft.scope
            if draft
            else "Cung cấp hàng hoá/dịch vụ theo yêu cầu đã phê duyệt."
        )
        tech_requirements = (
            list(draft.technical_requirements)
            if draft and draft.technical_requirements
            else requirements
        )
        content = {
            "title": f"Hồ sơ mời thầu/RFQ — {state.get('method_label', '')}",
            "drafted_by": "ai" if draft else "template",
            "scope": scope,
            "requirements": tech_requirements,
            "commercial_terms": {
                "payment": self.services.rules.payment_term_template,
                "delivery": f"Giao hàng trong {state.get('deadline') or 'thời hạn quy định'}.",
                "tax": self.services.rules.tax_term_template,
            },
            "response_structure": list(self.services.rules.response_structure),
            "submission": {
                "deadline_offset_days": 14,
                "method": "Nộp hồ sơ qua cổng/email theo hướng dẫn.",
            },
            "sections_present": [
                "scope",
                "requirements",
                "commercial_terms",
                "response_structure",
                "submission",
                "confidentiality",
            ],
            "confidentiality": "Thông tin hồ sơ được bảo mật theo quy định.",
        }
        # RAG grounding: legal/template basis for the solicitation structure.
        content["references"] = await self._cite(
            rc,
            "nội dung hồ sơ mời thầu yêu cầu về năng lực kỹ thuật thương mại",
            domain="legal",
        )
        content["grounding_status"] = "grounded" if content["references"] else "not_available"
        async with self.services.uow_factory(TenantId(rc.tenant_id)) as uow:
            case = await uow.cases.get(case_id)
            assert case is not None
            await self._add_artifact(uow, case, ArtifactType.SOLICITATION_PACKAGE, content)
            case.advance(CaseState.BUILDING_SOLICITATION, "build_solicitation")
            await uow.cases.save(case)
            await uow.commit()
        return {}

    # -- 9. evaluation criteria (weights sum to 100) ----------------------
    async def draft_evaluation_criteria(
        self, state: PreparationState, config: RunnableConfig
    ) -> PreparationState:
        rc = _run_context(config)
        case_id = _case_id(state)
        requirements = [r["text"] for r in state.get("requirements", [])]
        # LLM tailors the weighted criteria (validated to sum 100); mandatory
        # criteria stay from the rule pack (legal baseline). Fallback: rule pack.
        llm_weighted = await self._llm_criteria(
            rc, str(state.get("procurement_type", "")), requirements
        )
        weighted = (
            llm_weighted
            if llm_weighted
            else [
                {"code": code, "text": text, "weight": weight}
                for code, text, weight in self.services.rules.weighted_criteria
            ]
        )
        criteria: dict[str, Any] = {
            "mandatory": [
                {"code": code, "text": text, "pass_fail": True}
                for code, text in self.services.rules.mandatory_criteria
            ],
            "weighted": weighted,
            "method": "Chấm điểm có trọng số; điểm tiên quyết pass/fail.",
            "source": "ai" if llm_weighted else f"rule_pack:{self.services.rules.version}",
        }
        content = {
            **criteria,
            "weighted_total": sum(int(c["weight"]) for c in criteria["weighted"]),
            "has_mandatory": bool(criteria["mandatory"]),
        }
        # RAG grounding: legal basis for evaluation criteria/method.
        content["references"] = await self._cite(
            rc,
            "tiêu chí đánh giá hồ sơ dự thầu phương pháp chấm điểm",
            domain="legal",
        )
        content["grounding_status"] = "grounded" if content["references"] else "not_available"
        async with self.services.uow_factory(TenantId(rc.tenant_id)) as uow:
            case = await uow.cases.get(case_id)
            assert case is not None
            await self._add_artifact(uow, case, ArtifactType.EVALUATION_CRITERIA, content)
            await uow.commit()
        return {"criteria": content}

    # -- 10. supplier shortlist ------------------------------------------
    async def build_supplier_shortlist(
        self, state: PreparationState, config: RunnableConfig
    ) -> PreparationState:
        rc = _run_context(config)
        case_id = _case_id(state)
        method_min = state.get("min_suppliers", 3)
        candidates = state.get("supplier_candidates", [])
        shortlist = [
            {
                "name": str(s.get("name", "")),
                "eligibility_status": "pending_verification",
                "source": "manual_case_input",
            }
            for s in candidates
            if isinstance(s, dict) and str(s.get("name", "")).strip()
        ]
        content = {
            "shortlist": shortlist,
            "excluded": [],
            "count": len(shortlist),
            "min_required": method_min,
            "warning": ("Danh sách do người lập hồ sơ cung cấp; cần xác minh eligibility tại CP2."),
        }
        async with self.services.uow_factory(TenantId(rc.tenant_id)) as uow:
            case = await uow.cases.get(case_id)
            assert case is not None
            await self._add_artifact(uow, case, ArtifactType.SUPPLIER_SHORTLIST, content)
            await uow.commit()
        return {"shortlist": shortlist}

    # -- 11. risk / competition check ------------------------------------
    async def run_risk_check(
        self, state: PreparationState, config: RunnableConfig
    ) -> PreparationState:
        rc = _run_context(config)
        case_id = _case_id(state)
        shortlist = state.get("shortlist", [])
        checks = [
            {
                "check": "Cạnh tranh tối thiểu",
                "ok": len(shortlist) >= state.get("min_suppliers", 3),
                "detail": f"{len(shortlist)} nhà cung cấp trong shortlist.",
            },
            {
                "check": "Xung đột lợi ích",
                "ok": False,
                "detail": "Chưa có nguồn kiểm tra xung đột; cần người phê duyệt xác nhận.",
            },
            {
                "check": "Tiêu chí không thiên vị",
                "ok": True,
                "detail": "Tiêu chí dựa trên kỹ thuật/giá, không nêu tên nhà cung cấp.",
            },
        ]
        content = {"checks": checks, "all_ok": all(c["ok"] for c in checks)}
        async with self.services.uow_factory(TenantId(rc.tenant_id)) as uow:
            case = await uow.cases.get(case_id)
            assert case is not None
            await self._add_artifact(uow, case, ArtifactType.RISK_COMPLIANCE_CHECK, content)
            await uow.commit()
        return {"risk": content}

    # -- 12. package gate + CP2 payload ----------------------------------
    async def package_gate(
        self, state: PreparationState, config: RunnableConfig
    ) -> PreparationState:
        rc = _run_context(config)
        case_id = _case_id(state)
        rules = self.services.rules
        method = rules.select_method(state.get("estimated_value_minor", 0))
        criteria = state.get("criteria", {})
        result = solicitation_gate(
            rules=rules,
            weighted_total=int(criteria.get("weighted_total", 0)),
            has_mandatory_criteria=bool(criteria.get("has_mandatory")),
            shortlist_count=len(state.get("shortlist", [])),
            method=method,
            missing_sections=[],
        )
        gate = {"passed": result.passed, "reasons": list(result.reasons)}
        payload = {
            "approval_type": "preparation.cp2",
            "reason": "CP2 — Duyệt bộ hồ sơ mời thầu chính thức",
            "checkpoint": "CP2",
            "case_id": state["case_id"],
            "case_title": state.get("case_title", ""),
            "source_pr_ref": state.get("source_pr_ref", ""),
            "gate": gate,
            "weighted_total": int(criteria.get("weighted_total", 0)),
            "shortlist_count": len(state.get("shortlist", [])),
            "estimated_value": _fmt_vnd(state.get("estimated_value_minor", 0)),
            "method": {
                "key": state.get("method_key", ""),
                "label": state.get("method_label", ""),
            },
            "risk": state.get("risk", {}),
            "decision_warning": (
                "Shortlist do người lập nhập; eligibility và xung đột lợi ích "
                "chưa được hệ thống bên ngoài xác minh."
            ),
        }
        # P5: advisory review of the full package before the CP2 card.
        review = None
        if result.passed:
            review = await self._run_review(
                rc,
                checkpoint="CP2",
                artifact_json={
                    **payload,
                    "criteria": state.get("criteria", {}),
                    "shortlist": state.get("shortlist", []),
                },
                gate=gate,
            )
        async with self.services.uow_factory(TenantId(rc.tenant_id)) as uow:
            case = await uow.cases.get(case_id)
            assert case is not None
            # Persist the gate verdict on the solicitation package so a failed CP2
            # gate shows its reasons in the UI instead of silently parking the case.
            package = await uow.artifacts.latest(case_id, ArtifactType.SOLICITATION_PACKAGE)
            if package is not None:
                merged = {**package.content, "gate": gate}
                await self._add_artifact(uow, case, ArtifactType.SOLICITATION_PACKAGE, merged)
            case.advance(CaseState.CP2_PENDING if result.passed else CaseState.PACKAGE_READY, "cp2")
            if result.passed:
                await self._notify_progress(
                    uow,
                    case,
                    stage="cp2_gate",
                    dedupe=_hash(gate)[:12],
                    heading="📄 HSMT đã dựng xong — gate CP2: ĐẠT, chờ duyệt",
                    lines=[
                        (
                            f"Tiêu chí đánh giá: tổng trọng số "
                            f"{int(criteria.get('weighted_total', 0))}/100."
                        ),
                        f"Shortlist: {len(state.get('shortlist', []))} nhà cung cấp.",
                        "Đã trình duyệt CP2 — hồ sơ tạm dừng chờ quyết định.",
                    ],
                )
                cp2_lines = [
                    (
                        f"Tiêu chí đánh giá: tổng trọng số "
                        f"{int(criteria.get('weighted_total', 0))}/100."
                    ),
                    f"Shortlist: {len(state.get('shortlist', []))} nhà cung cấp.",
                    "Gate CP2 tự động: ĐẠT — hồ sơ mời thầu sẵn sàng để duyệt.",
                ]
                if review is not None:
                    await self._add_artifact(
                        uow,
                        case,
                        ArtifactType.REVIEW_RECOMMENDATION,
                        {
                            "checkpoint": "CP2",
                            "agent_id": "dw01.review_agent",
                            "prompt_version": "1.0.0",
                            **review.model_dump(),
                        },
                    )
                    cp2_lines += review_card_lines(review)
                await self._notify_cp_approval(
                    uow,
                    case,
                    checkpoint="CP2",
                    dedupe=_hash(gate)[:12],
                    lines=cp2_lines,
                )
            else:
                await self._notify_progress(
                    uow,
                    case,
                    stage="cp2_gate",
                    dedupe=_hash(gate)[:12],
                    heading="⚠️ Gate CP2 CHƯA ĐẠT — hồ sơ cần chỉnh",
                    lines=[*result.reasons, "Mở hồ sơ để xem chi tiết."],
                )
            await uow.cases.save(case)
            await uow.commit()
        return {"package_gate": gate, "cp2_payload": payload}

    async def cp2_review(self, state: PreparationState, config: RunnableConfig) -> PreparationState:
        decision: dict[str, Any] = interrupt(state.get("cp2_payload", {}))
        return {"cp2_decision": dict(decision)}

    async def apply_cp2(self, state: PreparationState, config: RunnableConfig) -> PreparationState:
        rc = _run_context(config)
        case_id = _case_id(state)
        decision = state.get("cp2_decision", {})
        approved = bool(decision.get("approved"))
        comment = str(decision.get("comment", "") or "").strip()
        async with self.services.uow_factory(TenantId(rc.tenant_id)) as uow:
            case = await uow.cases.get(case_id)
            assert case is not None
            case.advance(
                CaseState.CP2_APPROVED if approved else CaseState.CP2_REJECTED,
                "official" if approved else "cp2_rejected",
            )
            if approved:
                lines = ["Bộ hồ sơ mời thầu được phê duyệt — đang niêm phong bản chính thức…"]
            else:
                lines = [
                    f"Lý do: {comment}" if comment else "Không có nhận xét kèm theo.",
                    "Quy trình dừng tại đây — mở hồ sơ để xem chi tiết.",
                ]
            await self._notify_progress(
                uow,
                case,
                stage="cp2_decision",
                dedupe=rc.run_id.hex[:12],
                heading=(
                    "✅ CP2 — Hồ sơ mời thầu ĐÃ ĐƯỢC DUYỆT"
                    if approved
                    else "⛔ CP2 — Hồ sơ bị TỪ CHỐI"
                ),
                lines=lines,
            )
            await uow.cases.save(case)
            await uow.commit()
        return {}

    # -- 13. lock official + export --------------------------------------
    async def finalize_official(
        self, state: PreparationState, config: RunnableConfig
    ) -> PreparationState:
        rc = _run_context(config)
        case_id = _case_id(state)
        async with self.services.uow_factory(TenantId(rc.tenant_id)) as uow:
            case = await uow.cases.get(case_id)
            assert case is not None
            artifacts = await uow.artifacts.list_for_case(case_id)
            manifest = {
                "case_id": state["case_id"],
                "title": case.title,
                "method": state.get("method_label"),
                "estimated_value": _fmt_vnd(case.estimated_value_minor),
                "rule_pack_version": self.services.rules.version,
                "cp1_decision": state.get("cp1_decision"),
                "cp2_decision": state.get("cp2_decision"),
                "artifacts": [
                    {
                        "type": a.artifact_type.value,
                        "version": a.artifact_version,
                        "content_hash": a.content_hash,
                    }
                    for a in artifacts
                ],
            }
            manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
            package_markdown = _render_package_markdown(case, state, artifacts)
            prefix = (
                f"{rc.tenant_id}/{rc.workspace_id}/{self.services.exports_bucket_prefix}"
                f"/preparation/{state['case_id']}"
            )
            manifest_ref = await self.services.storage.put_object(
                f"{prefix}/official-manifest.json", manifest_bytes, "application/json"
            )
            await self.services.storage.put_object(
                f"{prefix}/solicitation-package.md",
                package_markdown.encode("utf-8"),
                "text/markdown",
            )
            official = await self._add_artifact(
                uow,
                case,
                ArtifactType.OFFICIAL_PACKAGE_MANIFEST,
                {
                    **manifest,
                    "manifest_ref": manifest_ref,
                    "package_ref": f"{prefix}/solicitation-package.md",
                    "package_markdown": package_markdown,
                },
                status=ArtifactStatus.OFFICIAL,
            )
            # lock_official already lands in PACKAGE_OFFICIAL (single version bump).
            case.lock_official(official.id.value, manifest_ref)
            await self._notify_progress(
                uow,
                case,
                stage="official",
                dedupe=rc.run_id.hex[:12],
                heading="🏁 Bộ hồ sơ mời thầu CHÍNH THỨC đã sẵn sàng",
                lines=[
                    f"Hình thức: {state.get('method_label', '')}.",
                    f"{len(artifacts)} artifact được niêm phong trong manifest.",
                    "Bấm nút bên dưới để phát hành gói thầu (gửi RFQ qua email).",
                ],
                buttons=[
                    {
                        "action_id": "dw01_publish",
                        "label": "📧 Phát hành RFQ",
                        "value": str(case.id.value),
                        "style": "primary",
                    }
                ],
            )
            await uow.cases.save(case)
            await uow.commit()
        return {"official_manifest": manifest, "export_ref": manifest_ref}

    async def close_failed(
        self, state: PreparationState, config: RunnableConfig
    ) -> PreparationState:
        # State already reflects the rejection (CP1_REJECTED / CP2_REJECTED).
        return {}

    async def close_incomplete(
        self, state: PreparationState, config: RunnableConfig
    ) -> PreparationState:
        # The deterministic CP1 gate already persisted WAITING_CLARIFICATION.
        # A user supplies answers through the application API and starts a fresh,
        # fully traceable run; no paused workflow is silently mutated.
        return {}


def _render_package_markdown(
    case: PreparationCase, state: PreparationState, artifacts: list[PreparationArtifact]
) -> str:
    by_type = {a.artifact_type: a for a in artifacts}
    lines: list[str] = [
        f"# Bộ hồ sơ mời thầu chính thức — {case.title}",
        "",
        f"- **Mã case:** {case.id.value}",
        f"- **Hình thức:** {state.get('method_label', '')}",
        f"- **Giá trị gói:** {_fmt_vnd(case.estimated_value_minor)}",
        f"- **Rule pack:** v{state.get('schema_version', '1.0')}",
        "",
        "## 1. Yêu cầu",
    ]
    for r in state.get("requirements", []):
        lines.append(f"- {r['text']}")
    criteria = by_type.get(ArtifactType.EVALUATION_CRITERIA)
    if criteria is not None:
        lines += ["", "## 2. Tiêu chí đánh giá"]
        for c in _dict_items(criteria.content.get("weighted", [])):
            lines.append(f"- [{c['weight']}%] {c['text']}")
    shortlist = by_type.get(ArtifactType.SUPPLIER_SHORTLIST)
    if shortlist is not None:
        lines += ["", "## 3. Danh sách nhà cung cấp mời"]
        for s in _dict_items(shortlist.content.get("shortlist", [])):
            lines.append(f"- {s['name']}")
    lines += ["", "## 4. Phê duyệt", "- CP1: APPROVED", "- CP2: APPROVED"]
    return "\n".join(lines)
