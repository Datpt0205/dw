"""Loads the DW01 procurement rule pack (YAML) into ``ProcurementRules``."""

from __future__ import annotations

from pathlib import Path

import yaml

from dw_kernel.errors import InfrastructureError
from dw_tender.application.preparation.rules import ApprovalTier, Method, ProcurementRules


def load_procurement_rules(path: Path) -> ProcurementRules:
    try:
        data = yaml.safe_load(path.read_bytes())
    except yaml.YAMLError as exc:  # pragma: no cover - defensive
        raise InfrastructureError(f"invalid rule pack: {path}") from exc
    if not isinstance(data, dict) or str(data.get("version")) != "1":
        raise InfrastructureError(f"unsupported rule pack schema: {path}")

    methods = tuple(
        Method(
            key=str(m["key"]),
            label=str(m["label"]),
            max_value=(None if m.get("max_value") is None else int(m["max_value"])),
            min_suppliers=int(m["min_suppliers"]),
        )
        for m in data["methods"]
    )
    tiers = tuple(
        ApprovalTier(
            max_value=(None if t.get("max_value") is None else int(t["max_value"])),
            cp1_role=str(t["cp1_role"]),
            cp2_role=str(t["cp2_role"]),
            cp3_role=str(t.get("cp3_role", t["cp1_role"])),
            cp4_role=str(t.get("cp4_role", t["cp1_role"])),
        )
        for t in data.get("approval_tiers", [])
    )
    evaluation = data.get("evaluation", {})
    solicitation = data.get("solicitation_template", {})
    intake = data.get("intake", {})
    repeat = data.get("repeat_purchase", {})
    return ProcurementRules(
        version=str(data["version"]),
        currency=str(data.get("currency", "VND")),
        methods=methods,
        weighted_total_must_equal=int(evaluation.get("weighted_total_must_equal", 100)),
        require_mandatory_criteria=bool(evaluation.get("require_mandatory_criteria", True)),
        legal_review_required_above=int(data.get("legal_review_required_above", 0)),
        finance_review_required_above=int(data.get("finance_review_required_above", 0)),
        tco_required_above=int(data.get("tco_required_above", 0)),
        specialist_review_above=int(data.get("specialist_review_above", 0)),
        require_approved_pr=bool(intake.get("require_approved_pr", True)),
        require_budget=bool(intake.get("require_budget", True)),
        require_deadline=bool(intake.get("require_deadline", True)),
        require_owner=bool(intake.get("require_owner", True)),
        mandatory_criteria=tuple(
            (str(item["code"]), str(item["text"])) for item in evaluation.get("mandatory", [])
        ),
        weighted_criteria=tuple(
            (str(item["code"]), str(item["text"]), int(item["weight"]))
            for item in evaluation.get("weighted", [])
        ),
        payment_term_template=str(solicitation.get("payment_term", "")),
        tax_term_template=str(solicitation.get("tax_term", "")),
        response_structure=tuple(str(item) for item in solicitation.get("response_structure", [])),
        approval_tiers=tiers,
        repeat_lookback_days=int(repeat.get("lookback_days", 0)),
        repeat_similarity=float(repeat.get("similarity", 0.0)),
        repeat_min_value=int(repeat.get("min_value", 0)),
    )
