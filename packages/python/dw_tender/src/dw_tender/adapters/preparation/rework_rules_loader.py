"""Loads the DW01 rework-support rule pack (YAML) into ``ReworkSupportRules``.

Kept separate from ``rules_loader.py`` because the two packs have different
lifecycles: the procurement matrix changes when the company's delegation of
authority changes, these thresholds change whenever procurement tunes them
against real numbers. Separate files mean separate ``policy_version`` counters,
and a blocking decision has to be traceable to the exact thresholds in force
when it was made.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from dw_kernel.errors import InfrastructureError
from dw_tender.application.preparation.rework import ReworkReason, ReworkSupportRules

_SUPPORTED_SCHEMA = "1.0"


def _int_at(data: dict[str, Any], section: str, key: str, path: Path) -> int:
    """Read one integer, naming the file when it is missing or the wrong type.

    The error has to carry the path: an operator who mistypes a threshold gets
    a startup failure, and "which of the rule packs" is the first thing they
    need to know.
    """
    block = data.get(section)
    if not isinstance(block, dict) or key not in block:
        raise InfrastructureError(f"rule pack missing {section}.{key}: {path}")
    try:
        return int(block[key])
    except (TypeError, ValueError) as exc:
        raise InfrastructureError(f"rule pack {section}.{key} must be an integer: {path}") from exc


def _parse_enabled_from(raw: Any, path: Path) -> datetime | None:
    if raw in (None, ""):
        return None
    if isinstance(raw, datetime):
        moment = raw
    else:
        try:
            moment = datetime.fromisoformat(str(raw))
        except ValueError as exc:
            raise InfrastructureError(f"rule pack enabled_from is not a datetime: {path}") from exc
    if moment.tzinfo is None:
        raise InfrastructureError(f"rule pack enabled_from must carry a timezone: {path}")
    return moment


def load_rework_support_rules(path: Path) -> ReworkSupportRules:
    try:
        data = yaml.safe_load(path.read_bytes())
    except yaml.YAMLError as exc:  # pragma: no cover - defensive
        raise InfrastructureError(f"invalid rule pack: {path}") from exc
    if not isinstance(data, dict) or str(data.get("schema_version")) != _SUPPORTED_SCHEMA:
        raise InfrastructureError(f"unsupported rule pack schema: {path}")

    raw_reasons = data.get("reason_codes") or []
    if not isinstance(raw_reasons, list):
        raise InfrastructureError(f"rule pack reason_codes must be a list: {path}")
    reasons: list[ReworkReason] = []
    for item in raw_reasons:
        if not isinstance(item, dict) or "code" not in item:
            raise InfrastructureError(f"rule pack reason entry needs a code: {path}")
        reasons.append(
            ReworkReason(
                code=str(item["code"]),
                label=str(item.get("label", "")).strip(),
                guidance=str(item.get("guidance", "")).strip(),
            )
        )

    explanation = data.get("explanation")
    if not isinstance(explanation, dict):
        raise InfrastructureError(f"rule pack missing explanation section: {path}")

    return ReworkSupportRules(
        policy_version=str(data.get("policy_version", "")),
        enabled_from=_parse_enabled_from(data.get("enabled_from"), path),
        nudge_window_days=_int_at(data, "nudge", "window_days", path),
        nudge_threshold=_int_at(data, "nudge", "threshold", path),
        block_window_days=_int_at(data, "block", "window_days", path),
        block_threshold=_int_at(data, "block", "threshold", path),
        explanation_min_chars=int(explanation.get("min_chars", 0)),
        supporter_role=str(explanation.get("supporter_role", "procurement_head")),
        escalate_after_hours=int(explanation.get("escalate_after_hours", 0)),
        general_guidance=str(data.get("general_guidance", "")).strip(),
        reason_codes=tuple(reasons),
    )
