"""Loads the DW01 procurement rule pack (YAML) into ``ProcurementRules``."""

from __future__ import annotations

from pathlib import Path

import yaml

from dw_kernel.errors import InfrastructureError
from dw_tender.application.preparation.rules import Method, ProcurementRules


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
    evaluation = data.get("evaluation", {})
    intake = data.get("intake", {})
    return ProcurementRules(
        version=str(data["version"]),
        currency=str(data.get("currency", "VND")),
        methods=methods,
        weighted_total_must_equal=int(evaluation.get("weighted_total_must_equal", 100)),
        require_mandatory_criteria=bool(evaluation.get("require_mandatory_criteria", True)),
        legal_review_required_above=int(data.get("legal_review_required_above", 0)),
        finance_review_required_above=int(data.get("finance_review_required_above", 0)),
        require_approved_pr=bool(intake.get("require_approved_pr", True)),
        require_budget=bool(intake.get("require_budget", True)),
        require_deadline=bool(intake.get("require_deadline", True)),
        require_owner=bool(intake.get("require_owner", True)),
    )
