"""The rule pack has to fail loudly, and name itself when it does.

Thresholds live in YAML so procurement can move them without a deploy. The
cost of that is a typo becoming a runtime behaviour change, so a malformed
pack must stop startup rather than silently fall back to a default — a support
mechanism quietly running on zeros looks exactly like one that is working.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dw_kernel.errors import InfrastructureError
from dw_tender.adapters.preparation.rework_rules_loader import load_rework_support_rules

pytestmark = pytest.mark.unit

REAL_PACK = (
    Path(__file__).resolve().parents[5] / "configs" / "policies" / "dw01" / "rework_support_v1.yaml"
)

MINIMAL = """
schema_version: "1.0"
policy_id: dw01_rework_support
policy_version: "9.9.9"
nudge: {window_days: 7, threshold: 3}
block: {window_days: 30, threshold: 5}
explanation: {min_chars: 80, supporter_role: procurement_head, escalate_after_hours: 48}
general_guidance: "chung"
reason_codes:
  - {code: a, label: "A", guidance: "ga"}
  - {code: b, label: "B", guidance: ""}
"""


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "pack.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_the_shipped_pack_loads() -> None:
    rules = load_rework_support_rules(REAL_PACK)
    assert rules.is_enabled()
    assert rules.policy_version
    assert rules.enabled_from is not None
    assert len(rules.reason_codes) == 7


def test_every_shipped_reason_has_a_label_and_guidance() -> None:
    """A blank advice slot on the card is worse than no card at all."""
    for reason in load_rework_support_rules(REAL_PACK).reason_codes:
        assert reason.label.strip(), reason.code
        assert reason.guidance.strip(), reason.code


def test_catalogue_order_is_preserved(tmp_path: Path) -> None:
    """Declaration order is the tie-break key, so the loader must not sort."""
    rules = load_rework_support_rules(_write(tmp_path, MINIMAL))
    assert [r.code for r in rules.reason_codes] == ["a", "b"]
    assert rules.rank_of("a") < rules.rank_of("b")


def test_an_unknown_schema_version_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, MINIMAL.replace('schema_version: "1.0"', 'schema_version: "2.0"'))
    with pytest.raises(InfrastructureError) as err:
        load_rework_support_rules(path)
    assert str(path) in str(err.value)


def test_a_missing_threshold_is_refused_and_names_the_file(tmp_path: Path) -> None:
    body = MINIMAL.replace("block: {window_days: 30, threshold: 5}", "block: {window_days: 30}")
    path = _write(tmp_path, body)
    with pytest.raises(InfrastructureError) as err:
        load_rework_support_rules(path)
    assert "block.threshold" in str(err.value)
    assert str(path) in str(err.value)


def test_a_non_integer_threshold_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, MINIMAL.replace("threshold: 3", 'threshold: "ba"'))
    with pytest.raises(InfrastructureError):
        load_rework_support_rules(path)


def test_a_missing_explanation_section_is_refused(tmp_path: Path) -> None:
    body = "\n".join(line for line in MINIMAL.splitlines() if not line.startswith("explanation:"))
    with pytest.raises(InfrastructureError):
        load_rework_support_rules(_write(tmp_path, body))


def test_a_naive_enabled_from_is_refused(tmp_path: Path) -> None:
    """Without a timezone the cutoff shifts by hours depending on where it runs."""
    path = _write(tmp_path, MINIMAL + '\nenabled_from: "2026-08-26T00:00:00"\n')
    with pytest.raises(InfrastructureError):
        load_rework_support_rules(path)


def test_an_absent_enabled_from_means_no_cutoff(tmp_path: Path) -> None:
    assert load_rework_support_rules(_write(tmp_path, MINIMAL)).enabled_from is None


def test_zero_thresholds_load_and_report_the_feature_off(tmp_path: Path) -> None:
    body = MINIMAL.replace("threshold: 3", "threshold: 0").replace("threshold: 5", "threshold: 0")
    assert load_rework_support_rules(_write(tmp_path, body)).is_enabled() is False


def test_a_reason_entry_without_a_code_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, MINIMAL + '  - {label: "no code"}\n')
    with pytest.raises(InfrastructureError):
        load_rework_support_rules(path)
