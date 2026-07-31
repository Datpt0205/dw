"""Independent Review Agent output schema (P5, plan §4.3).

The agent REVIEWS a submitted checkpoint artifact and recommends a decision —
it never decides. Its context is rebuilt from the submitted artifact + the
deterministic gate verdict only (no scratchpad access), and its output is
validated into this schema before anyone sees it.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ReviewVerdict = Literal["approve", "reject", "request_changes"]
CheckResult = Literal["pass", "warn", "fail"]


class ReviewCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check: str = Field(description="Tên hạng mục đã rà soát (tiếng Việt, ngắn)")
    result: CheckResult
    note: str = Field(default="", description="Ghi chú ngắn — dẫn chứng từ hồ sơ")


class ReviewRecommendation(BaseModel):
    """Structured advisory output shown on the approver's decision card."""

    model_config = ConfigDict(extra="forbid")

    recommendation: ReviewVerdict
    rationale_summary: str = Field(description="2-3 câu tiếng Việt: vì sao đề xuất như vậy")
    key_checks: list[ReviewCheck] = Field(default_factory=list, max_length=8)
    risks: list[str] = Field(default_factory=list, max_length=5)
    confidence: float = Field(ge=0.0, le=1.0)


_VERDICT_LABEL: dict[str, str] = {
    "approve": "ĐỀ XUẤT DUYỆT",
    "reject": "ĐỀ XUẤT TỪ CHỐI",
    "request_changes": "ĐỀ NGHỊ CHỈNH SỬA",
}


def review_card_lines(review: ReviewRecommendation) -> list[str]:
    """Render the recommendation as Slack card bullet lines (system-built)."""
    passed = sum(1 for c in review.key_checks if c.result == "pass")
    flagged = [c for c in review.key_checks if c.result != "pass"]
    lines = [
        (
            f"🤖 Review Agent: {_VERDICT_LABEL.get(review.recommendation, review.recommendation)}"
            f" (tin cậy {review.confidence:.0%})."
        ),
        f"Lý do: {review.rationale_summary}",
        f"Rà soát: {passed}/{len(review.key_checks)} hạng mục đạt.",
    ]
    for check in flagged[:3]:
        icon = "⚠️" if check.result == "warn" else "❌"
        lines.append(f"{icon} {check.check}: {check.note or check.result}")
    if review.risks:
        lines.append("Rủi ro: " + "; ".join(review.risks[:3]))
    return lines
