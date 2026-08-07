"""Channel-neutral decision engine for DW01 chat channels (Slack, Zalo, ...).

One source of truth for "a human decided something in chat": the pending list
comes from case states + the approval store (deterministic — no model guesses
what is decidable), decisions execute through the SAME application handlers the
web uses, and natural-language commands ("duyệt cp1", "từ chối", "xác minh")
map onto them. Channels only render the returned strings.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from dw_platform.application.access_context import AccessContext

if TYPE_CHECKING:
    from dw_api.bootstrap import ApiContainer
    from dw_tender.application.conversation.service import ConversationIntakeService

from uuid import UUID

# Action ids shared by button-based (Slack) and text-based (Zalo) channels.
INTAKE_APPROVE = "dw01_intake_approve"
INTAKE_REJECT = "dw01_intake_reject"
CP_APPROVE = "dw01_cp_approve"
CP_REJECT = "dw01_cp_reject"
CP4_CONFIRM = "dw01_cp4_confirm"
PUBLISH = "dw01_publish"
ADDENDUM_SUBMIT = "dw01_addendum_submit"
ADDENDUM_DISMISS = "dw01_addendum_dismiss"
OPEN_BIDS = "dw01_open_bids"

_REJECT_WORDS = ("từ chối", "khong duyệt", "không duyệt", "reject", "bỏ qua")
_APPROVE_WORDS = ("duyệt", "đồng ý", "approve", "xác minh", "xác nhận", "ok", "chốt")


@dataclass
class DecisionEngine:
    container: ApiContainer
    conversation_service: ConversationIntakeService
    channel_label: str = "chat"

    # ------------------------------------------------------------- pending --
    async def pending(self, context: AccessContext) -> list[dict[str, str]]:
        """Everything currently waiting for a human decision, workspace-wide."""
        preparation = self.container.preparation
        if preparation is None:
            return []
        out: list[dict[str, str]] = []
        cases = await preparation.list_cases.handle(context)
        for case in cases:
            if case.state == "draft":
                out.append(
                    {
                        "kind": "intake",
                        "cp": "",
                        "case_id": str(case.id),
                        "label": "Xác minh hồ sơ đầu vào",
                        "title": case.title,
                    }
                )
            elif case.state == "cp3_pending":
                out.append(
                    {
                        "kind": "cp",
                        "cp": "cp3",
                        "case_id": str(case.id),
                        "label": "CP3 — duyệt sửa đổi",
                        "title": case.title,
                    }
                )
            elif case.state == "cp4_ready":
                out.append(
                    {
                        "kind": "cp4",
                        "cp": "cp4",
                        "case_id": str(case.id),
                        "label": "CP4 — xác nhận mở thầu",
                        "title": case.title,
                    }
                )
        uow_factory = self.container.uow_factory
        if uow_factory is not None:
            titles = {str(case.id): case.title for case in cases}
            async with uow_factory(context) as uow:
                for request in await uow.approvals.list_pending():
                    if not request.approval_type.startswith("preparation.cp"):
                        continue
                    cp = request.approval_type.rsplit(".", 1)[-1]
                    case_id = str(request.payload.get("case_id", ""))
                    out.append(
                        {
                            "kind": "cp",
                            "cp": cp,
                            "case_id": case_id,
                            "label": f"{cp.upper()} — duyệt",
                            "title": titles.get(
                                case_id, str(request.payload.get("case_title", ""))
                            ),
                        }
                    )
        return out

    # -------------------------------------------------------- text parsing --
    async def try_text(self, text: str, context: AccessContext, display_name: str) -> str | None:
        """Natural-language decision ("duyệt cp1 đi") → reply text; None if
        the message is not a decision at all (let intake chat handle it)."""
        lowered = text.casefold()
        # Addendum in words (buttonless channels): "lập addendum gia hạn 7 ngày"
        # / "bỏ qua đề nghị sửa đổi" — checked BEFORE generic approve/reject so
        # "bỏ qua" does not fall through to a checkpoint rejection.
        if "addendum" in lowered or "sửa đổi hsmt" in lowered:
            if any(w in lowered for w in ("bỏ qua", "không lập", "thôi")):
                return "Đã bỏ qua đề nghị sửa đổi — HSMT giữ nguyên. (Người đề nghị sẽ được báo.)"
            if any(w in lowered for w in ("lập", "soạn", "đồng ý", "chốt")):
                return await self._submit_addendum_from_text(text, context, display_name)
        reject = any(w in lowered for w in _REJECT_WORDS)
        approve = not reject and any(w in lowered for w in _APPROVE_WORDS)
        if not (approve or reject):
            return None
        candidates = await self.pending(context)
        cp_match = re.search(r"cp\s*([1-4])", lowered)
        if cp_match:
            wanted = f"cp{cp_match.group(1)}"
            candidates = [c for c in candidates if c["cp"] == wanted]
        elif "xác minh" in lowered:
            candidates = [c for c in candidates if c["kind"] == "intake"]
        if not candidates:
            return "Hiện không có mục nào đang chờ bạn quyết định."
        if len(candidates) > 1:
            listing = "; ".join(f"{c['label']} ({c['title']})" for c in candidates)
            return f"Đang chờ nhiều mục: {listing}. Bạn ghi rõ giúp mình (vd: duyệt CP1)."
        target = candidates[0]
        if target["kind"] == "intake":
            action = INTAKE_APPROVE if approve else INTAKE_REJECT
            value = target["case_id"]
        elif target["kind"] == "cp4":
            if not approve:
                return "CP4 chỉ có bước xác nhận mở thầu — không có luồng từ chối."
            action, value = CP4_CONFIRM, target["case_id"]
        else:
            action = CP_APPROVE if approve else CP_REJECT
            value = f"{target['cp']}:{target['case_id']}"
        try:
            return await self.execute(action, value, context, display_name)
        except Exception as exc:  # surfaced to the user, never crashes the loop
            return f"⚠️ Không thực hiện được: {str(exc)[:200]}"

    # ------------------------------------------------------------ execute --
    async def execute(
        self, action_id: str, value: str, context: AccessContext, display_name: str
    ) -> str:
        preparation = self.container.preparation
        assert preparation is not None
        now = datetime.now(tz=UTC)
        via = f"qua {self.channel_label} bởi {display_name}"

        if action_id in (INTAKE_APPROVE, INTAKE_REJECT):
            case_id = UUID(value)
            if action_id == INTAKE_APPROVE:
                await preparation.verify_intake.handle(
                    case_id,
                    approval_reference=f"CHAT-{now:%Y%m%d-%H%M%S}",
                    comment=f"Xác minh {via}",
                    context=context,
                )
                return (
                    "✅ Đã xác minh intake — Digital Worker bắt đầu chạy. "
                    "Người tạo hồ sơ sẽ nhận tiến độ từng bước."
                )
            await preparation.reject_intake.handle(
                case_id, comment=f"Từ chối {via}", context=context
            )
            return "❌ Đã từ chối hồ sơ — người tạo sẽ nhận thông báo kèm lý do."

        if action_id == ADDENDUM_DISMISS:
            return "Đã bỏ qua đề nghị sửa đổi — HSMT giữ nguyên. (Người đề nghị sẽ được báo.)"

        if action_id == ADDENDUM_SUBMIT:
            from dw_tender.application.preparation.handlers import SubmitAddendumCommand

            proposal = json.loads(value)
            case_id = UUID(str(proposal["case_id"]))
            change = str(proposal.get("change", "")).strip()
            impact = str(proposal.get("impact", "")).strip()
            proposer = str(proposal.get("proposer", "người yêu cầu"))
            # Draft with the SAME pipeline as chat (LLM body + verbatim quote),
            # but under the procurement user's identity — they are the filer.
            markdown = await self.conversation_service._addendum_markdown(
                case_id=case_id,
                channel_key=f"case:{case_id}",
                change=change,
                impact=impact,
                raw_text=f"(đề nghị của {proposer}) {change}",
                display_name=display_name,
                context=context,
            )
            await preparation.submit_addendum.handle(
                case_id,
                SubmitAddendumCommand(
                    filename="addendum-from-proposal.md",
                    content_type="text/markdown; charset=utf-8",
                    content=markdown.encode("utf-8"),
                    change_summary=change,
                    impact_summary=impact,
                ),
                context,
            )
            return (
                f"📝 Đã lập addendum từ đề nghị của {proposer} và trình CP3 — "
                "thẻ quyết định sẽ tới người có thẩm quyền."
            )

        if action_id in (CP_APPROVE, CP_REJECT):
            cp, _, case_raw = value.partition(":")
            case_id = UUID(case_raw)
            approve = action_id == CP_APPROVE
            if cp == "cp3":
                # CP3 is a domain decision (no LangGraph interrupt behind it).
                await preparation.decide_cp3.handle(
                    case_id,
                    approve=approve,
                    approval_reference=f"CHAT-{now:%Y%m%d-%H%M%S}",
                    comment=f"Quyết định {via}",
                    context=context,
                )
                return (
                    "✅ Đã duyệt CP3 — addendum có hiệu lực."
                    if approve
                    else "⛔ Đã từ chối CP3 — HSMT giữ nguyên."
                )
            approval_id = await self._find_pending_approval(cp, case_id, context)
            if approval_id is None:
                return (
                    "⚠️ Không còn yêu cầu phê duyệt đang chờ cho checkpoint này "
                    "(có thể đã được quyết định)."
                )
            await self.container.approval_flow.decide(  # type: ignore[union-attr]
                approval_id=approval_id,
                approve=approve,
                comment=f"Quyết định {via}",
                context=context,
                authorization=self.container.authorization,
            )
            label = cp.upper()
            if not approve:
                return f"⛔ Đã từ chối {label} — quy trình dừng, người tạo sẽ được thông báo."
            if cp == "cp2":
                # CP2 per B5.4 IS the publication authorization ("cho phép
                # phát hành") — publish immediately, no extra human click.
                try:
                    result = await preparation.auto_publish.handle(case_id, context)
                    sent_to = str(result.get("sent_to", "")) if isinstance(result, dict) else ""
                    suffix = f" tới {sent_to}" if sent_to else ""
                    return (
                        "✅ Đã duyệt CP2 — bộ hồ sơ niêm phong bản chính thức "
                        f"và RFQ đã phát hành qua email{suffix}."
                    )
                except Exception as exc:
                    return (
                        "✅ Đã duyệt CP2 — hồ sơ đã niêm phong, nhưng phát hành "
                        f"tự động chưa chạy được ({str(exc)[:160]}). "
                        "Người tạo có thể yêu cầu phát hành lại qua chat."
                    )
            if cp == "cp1":
                return (
                    "✅ Đã duyệt CP1 — mình đang soạn hồ sơ mời thầu và tiêu chí, "
                    "sẽ trình CP2 trong ít phút."
                )
            return f"✅ Đã duyệt {label} — quy trình tiếp tục chạy tự động."

        if action_id == CP4_CONFIRM:
            from dw_tender.application.preparation.handlers import CompleteCp4Command

            case_id = UUID(value)
            # Biên bản do hệ thống lập từ hồ sơ (danh mục HSDT nằm trong sổ
            # tiếp nhận đã niêm phong) — không ai phải upload file.
            minutes_md = (
                f"# Biên bản mở thầu\n\n"
                f"- Thời điểm mở: {now:%d/%m/%Y %H:%M} (UTC)\n"
                f"- Người xác nhận: {display_name} (qua {self.channel_label})\n"
                f"- Danh mục hồ sơ dự thầu: theo sổ tiếp nhận (SUBMISSION_REGISTER) "
                f"đã niêm phong trong hồ sơ.\n"
                f"- Ghi chú: biên bản do hệ thống lập tự động trong môi trường mô phỏng.\n"
            )
            await preparation.complete_cp4.handle(
                case_id,
                CompleteCp4Command(
                    filename="bid-opening-minutes.md",
                    content_type="text/markdown; charset=utf-8",
                    content=minutes_md.encode("utf-8"),
                    opening_at=now.isoformat(),
                    witnesses=(display_name,),
                    approval_reference=f"CHAT-{now:%Y%m%d-%H%M%S}",
                    comment=f"Xác nhận CP4 {via}",
                ),
                context,
            )
            return (
                "CP4 hoàn tất — biên bản mở thầu đã lập, gói bàn giao DW02 đã "
                "niêm phong. Quy trình DW01 kết thúc."
            )

        if action_id == OPEN_BIDS:
            from dw_kernel.errors import ConflictError, DomainError

            case_id = UUID(value)
            try:
                count = await preparation.request_cp4.handle(case_id, context)
            except (ConflictError, DomainError):
                return (
                    "⚠️ Chưa có hồ sơ dự thầu nào được ghi nhận — báo nhà cung cấp "
                    "nộp qua email trước rồi mới chốt sổ nhé."
                )
            return (
                f"Đã chốt sổ với {count} hồ sơ dự thầu — thẻ xác nhận mở thầu (CP4) "
                "sẽ đến ngay sau đây."
            )

        if action_id == PUBLISH:
            case_id = UUID(value)
            result = await preparation.auto_publish.handle(case_id, context)
            recipient = str(result.get("recipient", "")) if isinstance(result, dict) else ""
            suffix = f" tới {recipient}" if recipient else ""
            return f"Đã phát hành RFQ qua email{suffix} và ghi nhận phát hành vào hồ sơ."

        raise ValueError(f"unknown action {action_id}")

    async def _submit_addendum_from_text(
        self, text: str, context: AccessContext, display_name: str
    ) -> str:
        """Buttonless addendum filing: the procurement user types the change.

        Targets the (single) case currently PUBLISHED — the only state that
        accepts an addendum; asks to disambiguate when several are.
        """
        preparation = self.container.preparation
        assert preparation is not None
        published = [
            c for c in await preparation.list_cases.handle(context) if c.state == "published"
        ]
        if not published:
            return "Hiện không có hồ sơ nào đang phát hành để lập addendum."
        if len(published) > 1:
            listing = "; ".join(c.title for c in published)
            return f"Có nhiều hồ sơ đang phát hành ({listing}) — bạn nêu rõ tên hồ sơ giúp mình."
        lowered = text.casefold()
        marker = lowered.find("addendum")
        change = text[marker + len("addendum") :].strip(" :,-—.") if marker >= 0 else ""
        if len(change) < 10:
            return (
                "Bạn nhắn kèm nội dung sửa đổi giúp mình nhé — ví dụ: "
                "«lập addendum gia hạn nộp thầu thêm 7 ngày»."
            )
        value = json.dumps(
            {
                "case_id": str(published[0].id),
                "change": change[:600],
                "impact": "",
                "proposer": display_name,
            },
            ensure_ascii=False,
        )
        return await self.execute(ADDENDUM_SUBMIT, value, context, display_name)

    async def _find_pending_approval(
        self, cp: str, case_id: UUID, context: AccessContext
    ) -> UUID | None:
        uow_factory = self.container.uow_factory
        if uow_factory is None:
            return None
        wanted_type = f"preparation.{cp}"
        async with uow_factory(context) as uow:
            for request in await uow.approvals.list_pending():
                if request.approval_type == wanted_type and str(
                    request.payload.get("case_id", "")
                ) == str(case_id):
                    return request.id
        return None
