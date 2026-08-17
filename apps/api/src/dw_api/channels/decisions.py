"""Channel-neutral decision engine for DW01 chat channels (Slack, Zalo, ...).

One source of truth for "a human decided something in chat": the pending list
comes from case states + the approval store (deterministic — no model guesses
what is decidable), decisions execute through the SAME application handlers the
web uses, and natural-language commands ("duyệt cp1", "từ chối", "xác minh")
map onto them. Channels only render the returned strings.
"""

from __future__ import annotations

import contextlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from dw_agent_runtime.ports import ModelRequest
from dw_platform.application.access_context import AccessContext
from dw_tender.application.conversation.schemas import DecisionIntent
from dw_tender.application.conversation.service import rank_by_label

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


def _match_by_title(text: str, candidates: list[dict[str, str]]) -> list[dict[str, str]]:
    """Candidates whose case title the message actually names.

    Same split as the conversation service: the person says it however they
    like, deterministic code decides which case that refers to. Returns the
    original list when nothing matches, so the caller still asks rather than
    picking at random.
    """
    # People point at a case however it was shown to them — by what it is
    # ("vụ laptop") or by who asked for it ("hồ sơ do Lê Thu Hà yêu cầu"). The
    # listing prints both, so both have to be matchable; leaving the name out
    # made the message miss entirely and fall through to intake chat, whose
    # guardrail then answered as if authority had been refused.
    labels = [f"{c.get('title', '')} {c.get('owner_name', '')}".strip() for c in candidates]
    scores = rank_by_label(text, labels)
    best = max(scores, default=0.0)
    if best <= 0 or scores.count(best) > 1:  # nothing named, or named ambiguously
        return candidates
    return [candidates[scores.index(best)]]


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
                # Separation of duties: the intake handler refuses whoever
                # filed the case, so never offer it back to them either.
                if case.created_by == context.principal_id:
                    continue
                out.append(
                    {
                        "kind": "intake",
                        "cp": "",
                        "case_id": str(case.id),
                        "label": "Xác minh hồ sơ đầu vào",
                        "title": case.title,
                        "owner_name": case.owner_name,
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
                        "owner_name": case.owner_name,
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
                        "owner_name": case.owner_name,
                    }
                )
        uow_factory = self.container.uow_factory
        if uow_factory is not None:
            titles = {str(case.id): case.title for case in cases}
            owners = {str(case.id): case.owner_name for case in cases}
            async with uow_factory(context) as uow:
                for request in await uow.approvals.list_pending():
                    if not request.approval_type.startswith("preparation.cp"):
                        continue
                    # Authority rides on the request itself, stamped from the
                    # versioned matrix. Offering a checkpoint the write path
                    # will refuse is worse than not offering it: the person
                    # says "duyệt" and gets an error instead of an answer.
                    required_role = str(request.payload.get("required_role", "") or "")
                    if required_role and required_role not in context.roles:
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
                            "owner_name": owners.get(case_id, ""),
                        }
                    )
        return out

    # -------------------------------------------------------- text parsing --
    async def try_text(self, text: str, context: AccessContext, display_name: str) -> str | None:
        """Natural-language decision ("duyệt cp1 đi") → reply text; None if
        the message is not a decision at all (let intake chat handle it)."""
        lowered = text.casefold()
        # Nothing pending -> nothing to decide, and no reason to spend a model
        # call. Also the cheap guard that keeps ordinary intake chat at one call.
        candidates = await self.pending(context)
        if not candidates:
            return None
        intent = await self._decision_intent(text, candidates, context)
        if intent.decision == "none":
            return None
        approve = intent.decision == "approve"
        cp_match = re.search(r"cp\s*([1-4])", lowered)
        if cp_match:
            wanted = f"cp{cp_match.group(1)}"
            candidates = [c for c in candidates if c["cp"] == wanted]
        elif intent.stage == "intake":
            candidates = [c for c in candidates if c["kind"] == "intake"]
        elif intent.stage == "checkpoint":
            candidates = [c for c in candidates if c["kind"] != "intake"]
        if not candidates:  # named a checkpoint that has nothing pending
            return "Hiện không có mục nào như vậy đang chờ bạn quyết định."
        if len(candidates) > 1:
            # Several packages can sit on the same checkpoint, so the number
            # alone does not identify one. Narrow by the case title the message
            # names ("duyệt cp2 vụ laptop") before giving up and asking.
            # Match against what the PERSON wrote, never the model's `target`:
            # asked to pick from a list, a model will happily name one even when
            # the message named nothing ("xác minh" -> target "Mua 20 tivi…"),
            # and that is a decision it has no business making.
            named = _match_by_title(text, candidates)
            if len(named) == 1:
                candidates = named
        if len(candidates) > 1:
            listing = "\n".join(
                f"  {c['label']} — {c['title']} (do {c['owner_name']} đề nghị)" for c in candidates
            )
            return (
                f"Đang chờ {len(candidates)} mục:\n{listing}\n"
                "👉 Bạn nói rõ hồ sơ nào giúp mình — vd «duyệt cp2 vụ laptop»."
            )
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

    async def _decision_intent(
        self, text: str, candidates: list[dict[str, str]], context: AccessContext
    ) -> DecisionIntent:
        """Ask the model whether this sentence IS a decision, and about what.

        A keyword table used to do this, and "ok" was in it — a bare "ok"
        answering something else approved the only pending item. The model
        reads the sentence; it is shown labels and titles only, never a case
        id, and code still resolves and executes the row. Any model failure
        degrades to "not a decision", which is the safe direction.
        """
        listing = "\n".join(
            f"- {c['label']} — {c['title']} — do {c['owner_name']} đề nghị" for c in candidates
        )
        try:
            return await self.conversation_service.gateway.generate_structured(
                ModelRequest(
                    task="conversation.decision_intent",
                    prompt_id="conversation.decision_intent",
                    prompt_version="1.0.0",
                    variables={"pending_items": listing, "message": text},
                    model_profile=self.conversation_service.model_profile,
                ),
                DecisionIntent,
                run_context=self.conversation_service._agent_run_context(
                    context, trace="decision", channel=self.channel_label.lower()
                ),
            )
        except Exception:
            return DecisionIntent()

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
                # channel_label is prose ("qua Zalo bởi …"); the trace dimension
                # is lowercase everywhere else. Same fact, one spelling.
                channel=self.channel_label.lower(),
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
            # Biên bản do hệ thống lập từ sổ tiếp nhận đã niêm phong — không ai
            # upload file, và nội dung không do model viết: một biên bản mở thầu
            # phải khớp từng dòng với thứ đã nhận, kể cả mã băm.
            minutes_md = await self._bid_opening_minutes(case_id, context, display_name, now)
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

    async def _bid_opening_minutes(
        self, case_id: UUID, context: AccessContext, display_name: str, now: datetime
    ) -> str:
        """Minutes that read like minutes: every bid received, named and hashed.

        The old version pointed at "the register" instead of reproducing it,
        which is the one thing a bid-opening record exists to do — state
        publicly what was in the box at the moment it was opened.
        """
        preparation = self.container.preparation
        assert preparation is not None
        rows: list[str] = []
        with contextlib.suppress(Exception):
            view = await preparation.get_case.handle(case_id, context)
            for artifact in view.artifacts:
                if artifact.artifact_type != "submission_register":
                    continue
                rows = [
                    f"| {i} | {item.get('supplier_name', '—')} "
                    f"| {item.get('received_at', '—')} "
                    f"| {item.get('filename', '—')} "
                    f"| `{str(item.get('content_hash', ''))[:16]}…` "
                    f"| {item.get('receipt_status', '—')} |"
                    for i, item in enumerate(artifact.content.get("items", []), start=1)
                    if isinstance(item, dict)
                ]
        table = (
            "| # | Nhà cung cấp | Thời điểm tiếp nhận | Tệp | Mã băm | Tình trạng |\n"
            "| --- | --- | --- | --- | --- | --- |\n" + "\n".join(rows) + "\n"
            if rows
            else "_Không có hồ sơ dự thầu nào trong sổ tiếp nhận._\n"
        )
        return (
            f"# Biên bản mở thầu\n\n"
            f"- Thời điểm mở: {now:%d/%m/%Y %H:%M} (UTC)\n"
            f"- Người xác nhận: {display_name} (qua {self.channel_label})\n"
            f"- Số hồ sơ dự thầu đã mở: {len(rows)}\n\n"
            f"## Danh mục hồ sơ dự thầu\n\n{table}\n"
            "Mã băm được ghi lúc tiếp nhận; sửa tệp sau thời điểm đó là mã băm "
            "lệch ngay.\n\n"
            "- Ghi chú: biên bản do hệ thống lập tự động trong môi trường mô phỏng.\n"
        )

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
