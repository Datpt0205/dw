"""Typed slot state + LLM turn schema for the DW01 chat intake.

"LLM drafts; deterministic code decides": the model only *extracts* slots and
*phrases* the next reply. Which fields are required, when the case may be
created and how many suppliers are needed all come from deterministic code and
the versioned rule pack — never from the model.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from dw_tender.application.preparation.rules import ProcurementRules


class IntakeSlots(BaseModel):
    """Everything the chat has collected so far. All optional until confirmed."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, description="Tên gói mua sắm ngắn gọn")
    item_summary: str | None = Field(
        default=None, description="Hàng hoá/dịch vụ chính cần mua (vd: laptop cho developer)"
    )
    quantity: int | None = Field(default=None, ge=1, description="Số lượng")
    estimated_value_vnd: int | None = Field(
        default=None, ge=1, description="Ngân sách dự kiến, VND (đồng), số nguyên"
    )
    deadline_days: int | None = Field(
        default=None, ge=1, le=3650, description="Thời hạn cần hàng, tính bằng SỐ NGÀY"
    )
    delivery_location: str | None = Field(default=None, description="Địa điểm giao hàng")
    purpose: str | None = Field(default=None, description="Mục đích/nhóm người dùng")
    supplier_names: list[str] = Field(
        default_factory=list, description="Các nhà cung cấp dự kiến mời (tên công ty)"
    )
    # The 4 commercial items DW01 otherwise raises as clarifications (optional).
    warranty_months: int | None = Field(default=None, ge=1, description="Bảo hành tối thiểu, tháng")
    os_license: str | None = Field(
        default=None, description="Hệ điều hành / bản quyền phần mềm kèm theo"
    )
    payment_terms: str | None = Field(default=None, description="Điều khoản thanh toán")

    @field_validator("deadline_days", mode="before")
    @classmethod
    def _normalize_deadline(cls, value: object) -> object:
        # "hôm nay / ngày <hôm nay>" — the model counts today as 0 days.
        if isinstance(value, int) and value == 0:
            return 1
        if isinstance(value, int) and (value < 0 or value > 3650):
            return None
        return value

    @field_validator("quantity", "estimated_value_vnd", "warranty_months", mode="before")
    @classmethod
    def _drop_nonpositive(cls, value: object) -> object:
        # A busted extraction must never crash the whole turn — drop the slot
        # so the deterministic missing-field check simply asks again.
        if isinstance(value, int) and value < 1:
            return None
        return value

    def merged_with(self, update: IntakeSlots) -> IntakeSlots:
        """New non-empty values win; everything else is kept."""
        data = self.model_dump()
        for key, value in update.model_dump().items():
            if value is None:
                continue
            if isinstance(value, list) and not value:
                continue
            data[key] = value
        return IntakeSlots.model_validate(data)


ChatIntent = Literal[
    "create_request",
    "provide_info",
    "ask_status",
    "cancel",
    "other",
    # Working on several requests at once (the user juggles them in one chat):
    "switch_request",  # "quay lại vụ laptop", "làm nốt cái bàn ghế đi"
    "list_requests",  # "đang dở những gì thế?" — MY unfinished drafts
    "list_cases",  # "có bao nhiêu hồ sơ rồi?" — filed cases and where they stand
    # Post-publication lifecycle (only meaningful when the case exists):
    "request_addendum",
    "record_submission",
    "open_bids",
]


class AddendumRequest(BaseModel):
    """Details for a post-publication amendment (CP3)."""

    model_config = ConfigDict(extra="forbid")

    change_summary: str = Field(default="", description="Nội dung sửa đổi/làm rõ")
    impact_summary: str = Field(
        default="", description="Ảnh hưởng tới NCC/thời hạn (nếu người dùng nêu)"
    )


class SubmissionInfo(BaseModel):
    """A supplier bid submission reported through chat."""

    model_config = ConfigDict(extra="forbid")

    supplier_name: str = Field(default="", description="Tên nhà cung cấp nộp hồ sơ")
    external_reference: str = Field(default="", description="Mã tham chiếu/số văn bản nếu có")


class ClarificationAnswerItem(BaseModel):
    """One answered clarification, mapped from the user's natural reply."""

    model_config = ConfigDict(extra="forbid")

    clarification_id: str = Field(description="ID câu hỏi làm rõ được trả lời")
    answer: str = Field(description="Câu trả lời rút từ tin nhắn (hoặc gợi ý nếu user đồng ý)")


class ClarifyTurn(BaseModel):
    """Structured output when the case is waiting for clarifications."""

    model_config = ConfigDict(extra="forbid")

    answers: list[ClarificationAnswerItem] = Field(
        default_factory=list,
        description="CHỈ các câu hỏi mà tin nhắn này thực sự trả lời",
    )
    reply_vi: str = Field(description="Phản hồi tiếng Việt gửi lại Slack")


class IntakeChatTurn(BaseModel):
    """Structured output of one chat turn (validated model response)."""

    model_config = ConfigDict(extra="forbid")

    intent: ChatIntent
    slots: IntakeSlots = Field(
        default_factory=IntakeSlots,
        description="CHỈ những thông tin tin nhắn này cung cấp",
    )
    addendum: AddendumRequest | None = Field(
        default=None, description="Khi intent=request_addendum"
    )
    submission: SubmissionInfo | None = Field(
        default=None, description="Khi intent=record_submission"
    )
    target_request: str = Field(
        default="",
        description=(
            "Khi intent=switch_request: tên hàng hoá/hồ sơ người dùng muốn quay lại, "
            "chép đúng nhãn trong danh sách việc đang dở"
        ),
    )
    reply_vi: str = Field(description="Câu trả lời tiếng Việt gửi lại Slack")
    reasoning_summary: str = Field(default="", description="1-2 câu: đã hiểu gì / vì sao hỏi lại")


class ComposedReply(BaseModel):
    """LLM-composed Slack reply from system-verified facts (ADR-020)."""

    model_config = ConfigDict(extra="ignore")

    reply_vi: str = Field(min_length=1, max_length=1200)


class DecisionIntent(BaseModel):
    """Is this message a checkpoint decision, and about which case?

    The model reads the sentence; deterministic code still resolves WHICH
    pending item that is and executes it. ``target`` is a name the person used,
    never an id — the model is not shown case ids and cannot pick a row.
    """

    model_config = ConfigDict(extra="ignore")

    decision: Literal["approve", "reject", "none"] = "none"
    stage: Literal["intake", "checkpoint", "any"] = "any"
    target: str = Field(default="", description="Tên hồ sơ/hàng hoá người dùng nhắc tới, nếu có")


class CaseOverviewReply(BaseModel):
    """LLM-written portfolio answer. Every number it may use is supplied by
    code; the model only decides wording, grouping and what to point out."""

    model_config = ConfigDict(extra="ignore")

    reply_vi: str = Field(min_length=1, max_length=2000)


class AddendumDraftText(BaseModel):
    """LLM-drafted addendum body; metadata + raw quote stay system-built."""

    model_config = ConfigDict(extra="ignore")

    change_section: str = Field(min_length=1, max_length=2000)
    impact_section: str = Field(default="", max_length=2000)
    affected_clauses: list[str] = Field(default_factory=list)


# Field → label shown when asking for it. Order matters (asked in this order).
_REQUIRED_LABELS: tuple[tuple[str, str], ...] = (
    ("item_summary", "Hàng hoá/dịch vụ cần mua"),
    ("quantity", "Số lượng"),
    ("estimated_value_vnd", "Ngân sách dự kiến (VND)"),
    ("deadline_days", "Thời hạn cần hàng (số ngày hoặc ngày cụ thể)"),
    ("delivery_location", "Địa điểm giao hàng"),
)


_VND_UNIT = re.compile(r"(\d+(?:[.,]\d+)?)\s*(tỷ|tỉ|ty\b|triệu|tr\b)", re.IGNORECASE)
_VND_PLAIN = re.compile(r"\b(\d{1,3}(?:[.,]\d{3}){2,}|\d{7,})\b")


def parse_vnd_amounts(text: str) -> set[int]:
    """Deterministic VND mentions in a message — cross-check for LLM parsing.

    "2 tỷ" -> 2_000_000_000; "500 triệu"/"500tr" -> 500_000_000; plain digit
    runs (>=7 digits, optionally dot/comma-grouped). Advisory only: used to
    catch an LLM mis-conversion, never to silently override the user.
    """
    amounts: set[int] = set()
    for number, unit in _VND_UNIT.findall(text):
        value = float(number.replace(",", "."))
        scale = 1_000_000_000 if unit.lower() in ("tỷ", "tỉ", "ty") else 1_000_000
        amounts.add(round(value * scale))
    for raw in _VND_PLAIN.findall(text):
        amounts.add(int(raw.replace(".", "").replace(",", "")))
    return amounts


def missing_required(slots: IntakeSlots, rules: ProcurementRules) -> list[str]:
    """Deterministic completeness check driving the clarification loop.

    Supplier count is checked against the *rule pack* for the stated budget so
    chat asks for exactly what the CP1 gate will later demand.
    """
    missing = [label for field, label in _REQUIRED_LABELS if getattr(slots, field) in (None, "")]
    if slots.estimated_value_vnd:
        method = rules.select_method(slots.estimated_value_vnd)
        if len(slots.supplier_names) < method.min_suppliers:
            missing.append(
                f"Nhà cung cấp dự kiến mời (tối thiểu {method.min_suppliers} "
                f"cho phương án {method.label}, đang có {len(slots.supplier_names)})"
            )
    elif not slots.supplier_names:
        missing.append("Nhà cung cấp dự kiến mời")
    return missing


def render_pr_markdown(slots: IntakeSlots, *, requester: str, pr_ref: str) -> str:
    """Materialize the chat-collected request as the PR document DW01 ingests.

    The downstream workflow (extract_requirements) reads this exactly like an
    uploaded PR file; items the user skipped stay explicit so the existing
    clarification flow picks them up.
    """

    def line(value: object | None, fallback: str = "Chưa nêu trong trao đổi") -> str:
        return str(value) if value not in (None, "", []) else fallback

    suppliers = "\n".join(f"- {name}" for name in slots.supplier_names) or "- Chưa nêu"
    warranty = (
        f"{slots.warranty_months} tháng" if slots.warranty_months else "Chưa nêu trong trao đổi"
    )
    budget = (
        f"{slots.estimated_value_vnd:,}".replace(",", ".") if slots.estimated_value_vnd else "0"
    )
    deadline = f"{slots.deadline_days} ngày" if slots.deadline_days else "Chưa nêu trong trao đổi"
    return f"""# Phiếu đề nghị mua sắm (tạo từ Slack)

- Mã tham chiếu: {pr_ref}
- Người đề nghị: {requester}
- Kênh tiếp nhận: Slack (DW01 chat intake)

## 1. Nhu cầu

- Hàng hoá/dịch vụ: {line(slots.item_summary)}
- Số lượng: {line(slots.quantity)}
- Mục đích sử dụng: {line(slots.purpose)}

## 2. Ngân sách và thời hạn

- Ngân sách dự kiến: {budget} VND
- Thời hạn cần hàng: {deadline}
- Địa điểm giao hàng: {line(slots.delivery_location)}

## 3. Điều kiện thương mại

- Bảo hành tối thiểu: {warranty}
- Hệ điều hành / bản quyền: {line(slots.os_license)}
- Điều khoản thanh toán: {line(slots.payment_terms)}

## 4. Nhà cung cấp đề xuất

{suppliers}
"""
