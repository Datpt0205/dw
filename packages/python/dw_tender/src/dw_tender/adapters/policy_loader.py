"""Load the versioned deterministic scoring policy from configs/policies."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import yaml

from dw_tender.domain.exceptions import InvalidScoringConfigError
from dw_tender.domain.services.scoring_engine import ScoringPolicy


def load_scoring_policy(path: Path) -> ScoringPolicy:
    try:
        data = yaml.safe_load(path.read_bytes())
    except yaml.YAMLError as exc:
        raise InvalidScoringConfigError(f"invalid scoring policy YAML: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != "1.0":
        raise InvalidScoringConfigError(f"unsupported scoring policy schema in {path.name}")
    try:
        return ScoringPolicy(
            policy_version=str(data["policy_version"]),
            require_evidence_for_mandatory=bool(data["require_evidence_for_mandatory"]),
            disqualify_on_mandatory_fail=bool(data["disqualify_on_mandatory_fail"]),
            min_total_score=Decimal(str(data["min_total_score"])),
            score_decimal_places=int(data.get("score_decimal_places", 2)),
        )
    except KeyError as exc:
        raise InvalidScoringConfigError(f"scoring policy missing field: {exc}") from exc
