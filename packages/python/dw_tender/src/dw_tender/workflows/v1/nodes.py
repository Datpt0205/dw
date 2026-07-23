"""Tender graph nodes (blueprint §12.1).

LLM proposes; deterministic code decides. Every mandatory conclusion must be
grounded: a proposed quote that cannot be located in the source document yields
NO evidence and the scoring engine fails that criterion closed.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from dw_agent_runtime.context import access_context_from_run
from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.ports import ModelRequest
from dw_kernel.errors import DomainError, NotFoundError
from dw_kernel.ids import TenantId, WorkspaceId
from dw_knowledge.contracts import SearchQuery
from dw_knowledge.gateway import IngestDocumentCommand, KnowledgeGateway
from dw_memory.contracts import MemoryType
from dw_memory.policy import MemoryCandidate
from dw_tender.application.dto import (
    ComplianceAssessment,
    ExtractedRequirements,
    RecommendationDraft,
)
from dw_tender.domain.entities import (
    ComplianceFinding,
    DocumentKind,
    FindingStatus,
    Requirement,
    TenderRecommendation,
)
from dw_tender.domain.services.evidence_locator import locate_quote
from dw_tender.domain.value_objects.ids import RequirementId, TenderCaseId
from dw_tender.domain.value_objects.scoring import RequirementKind
from dw_tender.workflows.v1.services import TenderWorkflowServices
from dw_tender.workflows.v1.state import STATE_SCHEMA_VERSION, TenderState


def _run_context(config: RunnableConfig) -> RunContext:
    run_context = config.get("configurable", {}).get("run_context")
    if not isinstance(run_context, RunContext):
        raise DomainError("workflow config is missing the trusted run_context")
    return run_context


def _case_id(state: TenderState) -> TenderCaseId:
    raw = state.get("case_id")
    if not raw:
        raise DomainError("workflow state is missing case_id")
    return TenderCaseId(uuid.UUID(raw))


class TenderNodes:
    def __init__(self, services: TenderWorkflowServices) -> None:
        self.services = services

    # 1 INTAKE_CASE -------------------------------------------------------
    async def intake_case(self, state: TenderState, config: RunnableConfig) -> TenderState:
        run_context = _run_context(config)
        case_id = _case_id(state)
        async with self.services.uow_factory(TenantId(run_context.tenant_id)) as uow:
            case = await uow.cases.get(case_id)
            if case is None:
                raise NotFoundError("tender case not found")
            documents = await uow.documents.list_for_case(case_id)
        kinds = {d.kind for d in documents}
        if DocumentKind.RFQ not in kinds or DocumentKind.SUPPLIER_SUBMISSION not in kinds:
            raise DomainError("case requires an RFQ and at least one supplier submission")
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "document_meta": {
                str(d.id): {
                    "kind": d.kind.value,
                    "title": d.title,
                    "supplier_name": d.supplier_name,
                    "content_hash": d.content_hash,
                    "storage_key": d.storage_key,
                }
                for d in documents
            },
        }

    # 2 PARSE_DOCUMENTS ---------------------------------------------------
    async def parse_documents(self, state: TenderState, config: RunnableConfig) -> TenderState:
        texts: dict[str, str] = {}
        for doc_id, meta in state.get("document_meta", {}).items():
            raw = await self.services.storage.get_object(str(meta["storage_key"]))
            texts[doc_id] = raw.decode("utf-8")
        if not texts:
            raise DomainError("no documents to parse")
        return {"document_texts": texts}

    # 3 CLASSIFY_DOCUMENTS (+ knowledge ingestion) ------------------------
    async def classify_documents(self, state: TenderState, config: RunnableConfig) -> TenderState:
        run_context = _run_context(config)
        context = access_context_from_run(run_context)
        meta = dict(state.get("document_meta", {}))
        warnings = list(state.get("warnings", []))

        knowledge = self.services.knowledge
        if isinstance(knowledge, KnowledgeGateway):
            async with self.services.uow_factory(TenantId(run_context.tenant_id)) as uow:
                for doc_id, doc_meta in meta.items():
                    if doc_meta.get("knowledge_document_id"):
                        continue
                    text = state.get("document_texts", {}).get(doc_id, "")
                    if not text:
                        continue
                    ingested = await knowledge.ingest_document(
                        IngestDocumentCommand(
                            title=str(doc_meta["title"]),
                            content=text,
                            domain="tender",
                        ),
                        context,
                    )
                    doc_meta["knowledge_document_id"] = str(ingested.document_id)
                    await uow.documents.set_knowledge_document(
                        uuid.UUID(doc_id), ingested.document_id
                    )
                await uow.commit()
        else:  # knowledge gateway without ingestion (test double)
            warnings.append("knowledge_ingestion_skipped")
        return {"document_meta": meta, "warnings": warnings}

    # 4 EXTRACT_REQUIREMENTS ---------------------------------------------
    async def extract_requirements(self, state: TenderState, config: RunnableConfig) -> TenderState:
        run_context = _run_context(config)
        rfq_text = self._first_text_by_kind(state, DocumentKind.RFQ)
        extracted = await self.services.model_gateway.generate_structured(
            ModelRequest(
                task="structured_extraction",
                prompt_id="tender.extract_requirements",
                prompt_version=self.services.prompt_bundle_version,
                variables={"rfq": rfq_text},
                model_profile=self.services.model_profile,
            ),
            ExtractedRequirements,
            run_context=run_context,
        )
        if not extracted.requirements:
            raise DomainError("no requirements extracted from the RFQ")
        return {"requirements": [r.model_dump(mode="json") for r in extracted.requirements]}

    # 5 BUILD_REQUIREMENT_MATRIX -----------------------------------------
    async def build_requirement_matrix(
        self, state: TenderState, config: RunnableConfig
    ) -> TenderState:
        run_context = _run_context(config)
        case_id = _case_id(state)
        requirements = self._requirements_from_state(state, run_context, case_id)
        # Fail fast on invalid weights BEFORE any scoring happens.
        self.services.scoring_engine.validate_requirements(requirements)

        suppliers = sorted(
            {
                str(meta["supplier_name"])
                for meta in state.get("document_meta", {}).values()
                if meta.get("kind") == DocumentKind.SUPPLIER_SUBMISSION.value
                and meta.get("supplier_name")
            }
        )
        async with self.services.uow_factory(TenantId(run_context.tenant_id)) as uow:
            await uow.requirements.replace_for_case(case_id, requirements)
            await uow.commit()
        return {"matrix_suppliers": suppliers}

    # 6 RETRIEVE_POLICIES_AND_HISTORY ------------------------------------
    async def retrieve_policies_and_history(
        self, state: TenderState, config: RunnableConfig
    ) -> TenderState:
        run_context = _run_context(config)
        context = access_context_from_run(run_context)
        results = await self.services.knowledge.search(
            SearchQuery(text="chính sách mua hàng yêu cầu nhà cung cấp", domain="tender"),
            context,
        )
        return {"policy_evidence": [chunk.evidence.model_dump(mode="json") for chunk in results]}

    # 7 EXTRACT_SUPPLIER_RESPONSES + 8 SCORE_COMPLIANCE (LLM proposal) ----
    async def extract_supplier_responses(
        self, state: TenderState, config: RunnableConfig
    ) -> TenderState:
        run_context = _run_context(config)
        submissions = self._texts_by_kind(state, DocumentKind.SUPPLIER_SUBMISSION)
        requirements_text = json.dumps(state.get("requirements", []), ensure_ascii=False)
        submissions_text = "\n\n".join(
            f"=== {name} ===\n{text}" for name, text in submissions.items()
        )
        assessment = await self.services.model_gateway.generate_structured(
            ModelRequest(
                task="structured_extraction",
                prompt_id="tender.assess_compliance",
                prompt_version=self.services.prompt_bundle_version,
                variables={
                    "requirements": requirements_text,
                    "submissions": submissions_text,
                },
                model_profile=self.services.model_profile,
            ),
            ComplianceAssessment,
            run_context=run_context,
        )
        return {"assessed_findings": [f.model_dump(mode="json") for f in assessment.findings]}

    # 8 SCORE_COMPLIANCE (deterministic grounding + persistence) ----------
    async def score_compliance(self, state: TenderState, config: RunnableConfig) -> TenderState:
        run_context = _run_context(config)
        case_id = _case_id(state)
        submissions_text = self._texts_by_kind(state, DocumentKind.SUPPLIER_SUBMISSION)
        doc_by_supplier = self._doc_meta_by_supplier(state)

        findings: list[ComplianceFinding] = []
        warnings = list(state.get("warnings", []))
        for raw in state.get("assessed_findings", []):
            supplier = str(raw["supplier_name"])
            quote = str(raw.get("quote", ""))
            source_text = submissions_text.get(supplier, "")
            located = locate_quote(quote, source_text) if source_text else None

            evidence: tuple[dict[str, object], ...] = ()
            if located is not None:
                meta = doc_by_supplier.get(supplier, {})
                evidence = (
                    {
                        "evidence_id": str(self.services.id_generator.new_uuid()),
                        "source_document_id": str(
                            meta.get("knowledge_document_id") or meta.get("id") or uuid.UUID(int=0)
                        ),
                        "source_version": "1",
                        "quote": quote,
                        "start_offset": located.start_offset,
                        "end_offset": located.end_offset,
                        "relevance_score": 1.0,
                        "classification": "internal",
                        "provenance_hash": located.source_hash,
                    },
                )
            elif quote:
                warnings.append(f"quote_not_found:{supplier}:{raw['requirement_code']}")

            claimed = bool(raw.get("claimed_compliant"))
            if not claimed:
                status = FindingStatus.NON_COMPLIANT
            elif evidence:
                status = FindingStatus.COMPLIANT
            else:
                status = FindingStatus.MISSING_EVIDENCE  # claim without grounded quote

            findings.append(
                ComplianceFinding(
                    id=self.services.id_generator.new_uuid(),
                    tenant_id=TenantId(run_context.tenant_id),
                    workspace_id=WorkspaceId(run_context.workspace_id),
                    case_id=case_id,
                    requirement_code=str(raw["requirement_code"]),
                    supplier_name=supplier,
                    status=status,
                    raw_score=Decimal(str(raw.get("raw_score", 0))),
                    note=str(raw.get("note", "")),
                    evidence=evidence,
                )
            )

        async with self.services.uow_factory(TenantId(run_context.tenant_id)) as uow:
            await uow.findings.replace_for_case(case_id, findings)
            await uow.commit()
        return {"warnings": warnings}

    # 9 IDENTIFY_GAPS_AND_RISKS ------------------------------------------
    async def identify_gaps_and_risks(
        self, state: TenderState, config: RunnableConfig
    ) -> TenderState:
        run_context = _run_context(config)
        case_id = _case_id(state)
        async with self.services.uow_factory(TenantId(run_context.tenant_id)) as uow:
            findings = await uow.findings.list_for_case(case_id)
        risks: list[str] = []
        for finding in findings:
            if finding.status is FindingStatus.NON_COMPLIANT:
                risks.append(f"non_compliant:{finding.supplier_name}:{finding.requirement_code}")
            elif finding.status is FindingStatus.MISSING_EVIDENCE:
                risks.append(f"missing_evidence:{finding.supplier_name}:{finding.requirement_code}")
        return {"risks": risks}

    # 10 DRAFT_RECOMMENDATION --------------------------------------------
    async def draft_recommendation(self, state: TenderState, config: RunnableConfig) -> TenderState:
        run_context = _run_context(config)
        assessment_text = json.dumps(
            {
                "findings": state.get("assessed_findings", []),
                "risks": state.get("risks", []),
            },
            ensure_ascii=False,
        )
        draft = await self.services.model_gateway.generate_structured(
            ModelRequest(
                task="reasoning",
                prompt_id="tender.draft_recommendation",
                prompt_version=self.services.prompt_bundle_version,
                variables={"assessment": assessment_text},
                model_profile=self.services.model_profile,
            ),
            RecommendationDraft,
            run_context=run_context,
        )
        return {"draft_recommendation": draft.model_dump(mode="json")}

    # 11 DETERMINISTIC_COMPLIANCE_GATE -----------------------------------
    async def deterministic_compliance_gate(
        self, state: TenderState, config: RunnableConfig
    ) -> TenderState:
        run_context = _run_context(config)
        case_id = _case_id(state)
        draft = state.get("draft_recommendation", {})

        async with self.services.uow_factory(TenantId(run_context.tenant_id)) as uow:
            requirements = await uow.requirements.list_for_case(case_id)
            findings = await uow.findings.list_for_case(case_id)

            outcome = self.services.scoring_engine.evaluate(
                requirements, findings, str(draft.get("recommended_supplier") or "")
            )
            # The GATE decides the final supplier — never the draft.
            evidence = [dict(e) for f in findings for e in f.evidence] + list(
                state.get("policy_evidence", [])
            )
            recommendation = TenderRecommendation(
                id=self.services.id_generator.new_uuid(),
                tenant_id=TenantId(run_context.tenant_id),
                workspace_id=WorkspaceId(run_context.workspace_id),
                case_id=case_id,
                scoring_policy_version=self.services.scoring_engine.policy.policy_version,
                recommended_supplier=outcome.top_supplier,
                rationale=str(draft.get("rationale", "")),
                supplier_scores=[s.as_dict() for s in outcome.scores],
                risks=list(state.get("risks", [])),
                evidence=evidence,
                gate_passed=outcome.gate_passed,
                gate_violations=list(outcome.violations),
                confidence=float(draft.get("confidence", 0.0)),
            )
            await uow.recommendations.upsert(recommendation)
            case = await uow.cases.get(case_id)
            if case is not None:
                case.mark_recommendation_ready()
                await uow.cases.save(case)
            await uow.commit()

        return {
            "gate_result": {
                "top_supplier": outcome.top_supplier,
                "gate_passed": outcome.gate_passed,
                "violations": list(outcome.violations),
                "scores": [s.as_dict() for s in outcome.scores],
            },
            "approval_payload": {
                "approval_type": "tender.approve_recommendation",
                "reason": "Phê duyệt khuyến nghị lựa chọn nhà cung cấp",
                "case_id": str(case_id),
                "recommended_supplier": outcome.top_supplier,
                "scores": [s.as_dict() for s in outcome.scores],
                "risks": list(state.get("risks", [])),
                "gate_violations": list(outcome.violations),
            },
        }

    # 12 HUMAN_REVIEW -----------------------------------------------------
    async def human_review(self, state: TenderState, config: RunnableConfig) -> TenderState:
        decision: dict[str, Any] = interrupt(state.get("approval_payload", {}))
        return {"approval_decision": dict(decision)}

    # 13 EXPORT_EVALUATION_PACK ------------------------------------------
    async def export_evaluation_pack(
        self, state: TenderState, config: RunnableConfig
    ) -> TenderState:
        run_context = _run_context(config)
        case_id = _case_id(state)
        decision = state.get("approval_decision", {})
        if not decision.get("approved"):
            return {"export_ref": "", "warnings": [*state.get("warnings", []), "not_approved"]}

        async with self.services.uow_factory(TenantId(run_context.tenant_id)) as uow:
            case = await uow.cases.get(case_id)
            requirements = await uow.requirements.list_for_case(case_id)
            findings = await uow.findings.list_for_case(case_id)
            recommendation = await uow.recommendations.get_for_case(case_id)

        pack = {
            "pack_version": "1.0",
            "case_id": str(case_id),
            "title": case.title if case else "",
            "generated_by_run": str(run_context.run_id),
            "requirements": [
                {
                    "code": r.code,
                    "statement": r.statement,
                    "kind": r.kind.value,
                    "weight": str(r.weight),
                }
                for r in requirements
            ],
            "findings": [
                {
                    "supplier": f.supplier_name,
                    "requirement": f.requirement_code,
                    "status": f.status.value,
                    "raw_score": str(f.raw_score),
                    "evidence": list(f.evidence),
                }
                for f in findings
            ],
            "recommendation": {
                "supplier": recommendation.recommended_supplier if recommendation else None,
                "rationale": recommendation.rationale if recommendation else "",
                "scores": recommendation.supplier_scores if recommendation else [],
                "gate_passed": recommendation.gate_passed if recommendation else False,
            },
            "approval": {
                "approved": True,
                "comment": str(decision.get("comment", "")),
            },
        }
        key = (
            f"{run_context.tenant_id}/{run_context.workspace_id}/"
            f"{self.services.exports_bucket_prefix}/tender/{case_id}/evaluation_pack.json"
        )
        export_ref = await self.services.storage.put_object(
            key,
            json.dumps(pack, ensure_ascii=False, indent=2).encode("utf-8"),
            "application/json",
        )
        return {"export_ref": export_ref}

    # 14 CLOSE_AND_WRITE_MEMORY ------------------------------------------
    async def close_and_write_memory(
        self, state: TenderState, config: RunnableConfig
    ) -> TenderState:
        run_context = _run_context(config)
        case_id = _case_id(state)
        export_ref = state.get("export_ref", "")

        async with self.services.uow_factory(TenantId(run_context.tenant_id)) as uow:
            case = await uow.cases.get(case_id)
            recommendation = await uow.recommendations.get_for_case(case_id)
            if case is not None and export_ref:
                case.complete(export_ref)
                await uow.cases.save(case)
            await uow.commit()

        memory_written = False
        if recommendation and recommendation.recommended_supplier and export_ref:
            first_evidence = next(
                (e for e in recommendation.evidence if e.get("provenance_hash")), None
            )
            if first_evidence is not None:
                from dw_knowledge.contracts import EvidenceRef

                result = await self.services.memory_service.propose(
                    MemoryCandidate(
                        worker_id=run_context.worker_id,
                        memory_type=MemoryType.EPISODIC,
                        content=(
                            f"Case '{case.title if case else case_id}': khuyến nghị "
                            f"{recommendation.recommended_supplier}, gate_passed="
                            f"{recommendation.gate_passed}."
                        ),
                        provenance_refs=(EvidenceRef.model_validate(first_evidence),),
                        confidence=0.9,
                    ),
                    access_context_from_run(run_context),
                    created_by_run_id=run_context.run_id,
                )
                memory_written = result.item is not None
        return {"memory_written": memory_written}

    # ------------------------------------------------------------ helpers --
    def _requirements_from_state(
        self, state: TenderState, run_context: RunContext, case_id: TenderCaseId
    ) -> list[Requirement]:
        requirements: list[Requirement] = []
        for raw in state.get("requirements", []):
            kind = RequirementKind(str(raw["kind"]))
            requirements.append(
                Requirement(
                    id=RequirementId(self.services.id_generator.new_uuid()),
                    tenant_id=TenantId(run_context.tenant_id),
                    workspace_id=WorkspaceId(run_context.workspace_id),
                    case_id=case_id,
                    code=str(raw["code"]),
                    statement=str(raw["statement"]),
                    kind=kind,
                    weight=(
                        Decimal(str(raw.get("weight", 0)))
                        if kind is RequirementKind.WEIGHTED
                        else Decimal(0)
                    ),
                )
            )
        return requirements

    def _first_text_by_kind(self, state: TenderState, kind: DocumentKind) -> str:
        for doc_id, meta in state.get("document_meta", {}).items():
            if meta.get("kind") == kind.value:
                return state.get("document_texts", {}).get(doc_id, "")
        raise DomainError(f"no document of kind {kind.value}")

    def _texts_by_kind(self, state: TenderState, kind: DocumentKind) -> dict[str, str]:
        result: dict[str, str] = {}
        for doc_id, meta in state.get("document_meta", {}).items():
            if meta.get("kind") == kind.value and meta.get("supplier_name"):
                result[str(meta["supplier_name"])] = state.get("document_texts", {}).get(doc_id, "")
        return result

    def _doc_meta_by_supplier(self, state: TenderState) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for doc_id, meta in state.get("document_meta", {}).items():
            if meta.get("supplier_name"):
                result[str(meta["supplier_name"])] = {**meta, "id": doc_id}
        return result
