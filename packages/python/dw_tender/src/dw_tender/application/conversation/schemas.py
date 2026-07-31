"""Typed slot state + LLM turn schema for the DW01 chat intake.

"LLM drafts; deterministic code decides": the model only *extracts* slots and
*phrases* the next reply. Which fields are required, when the case may be
created and how many suppliers are needed all come from deterministic code and
the versioned rule pack — never from the model.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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


ChatIntent = Literal["create_request", "provide_info", "ask_status", "cancel", "other"]


class IntakeChatTurn(BaseModel):
    """Structured output of one chat turn (validated model response)."""

    model_config = ConfigDict(extra="forbid")

    intent: ChatIntent
    slots: IntakeSlots = Field(
        default_factory=IntakeSlots,
        description="CHỈ những thông tin tin nhắn này cung cấp",
    )
    reply_vi: str = Field(description="Câu trả lời tiếng Việt gửi lại Slack")
    reasoning_summary: str = Field(
        default="", description="1-2 câu: đã hiểu gì / vì sao hỏi lại"
    )


# Field → label shown when asking for it. Order matters (asked in this order).
_REQUIRED_LABELS: tuple[tuple[str, str], ...] = (
    ("item_summary", "Hàng hoá/dịch vụ cần mua"),
    ("quantity", "Số lượng"),
    ("estimated_value_vnd", "Ngân sách dự kiến (VND)"),
    ("deadline_days", "Thời hạn cần hàng (số ngày hoặc ngày cụ thể)"),
    ("delivery_location", "Địa điểm giao hàng"),
)


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
                f"cho phương án «{method.label}», đang có {len(slots.supplier_names)})"
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
