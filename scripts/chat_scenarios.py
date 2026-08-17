"""Messy-conversation scenarios against the REAL model and a real database.

Unit tests pin the deterministic parts; this pins the parts that only break
when a person talks like a person — digressing, coming back, giving a bare
command, asking about the law in the middle of an intake. It runs the same
code path the Zalo channel runs, including the decision-engine suppression
rule, so a regression here is a regression a demo would show.

Not part of CI: it spends real model calls and needs the full stack.

    bash scripts/demo_reset.sh && bash scripts/seed_demo_cases.sh
    docker compose --env-file .env -f infra/compose/docker-compose.yml \
        exec -T api python - < scripts/chat_scenarios.py
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

import yaml

ROSTER = Path("/app/configs/demo/demo_users.yaml")

results: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> None:
    results.append((ok, name, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))


class Chat:
    """One person, one Zalo thread, replaying the channel's own ordering."""

    def __init__(self, container: Any, context: Any, name: str, key: str) -> None:
        from dw_api.channels.decisions import DecisionEngine

        self.svc = container.conversation_service
        self.engine = DecisionEngine(
            container=container, conversation_service=self.svc, channel_label="zalo"
        )
        self.context = context
        self.name = name
        self.key = key
        self.last_via_engine = False

    async def say(self, text: str, *, quiet: bool = False) -> str:
        active = await self.svc.store.find_active(
            tenant_id=self.context.tenant_id,
            workspace_id=self.context.workspace_id,
            channel_key=self.key,
        )
        self.last_via_engine = False
        if not self.svc.is_mid_intake(active):
            reply = await self.engine.try_text(text, self.context, self.name)
            if reply is not None:
                self.last_via_engine = True
                if not quiet:
                    print(f"    {self.name} > {text}\n    bot < [decision] {reply[:220]}")
                return reply
        outcome = await self.svc.handle_message(
            channel_key=self.key, text=text, context=self.context, display_name=self.name
        )
        reply = "\n".join(r.text for r in outcome.replies)
        if not quiet:
            print(f"    {self.name} > {text}\n    bot < {reply[:220]}")
        return reply


async def main() -> None:
    from dw_api import bootstrap
    from dw_platform.application.identity import VerifiedClaims

    container = bootstrap.build_container()
    assert container.conversation_service is not None
    preparation = container.preparation
    assert preparation is not None
    identity = container.access_context_factory
    assert identity is not None
    people = {u["subject"]: u for u in yaml.safe_load(ROSTER.read_text(encoding="utf-8"))["users"]}

    async def chat(subject: str, key: str) -> Chat:
        entry = people[subject]
        context = await identity.build(
            VerifiedClaims(subject=subject, email=None, issuer="dw-zalo"),
            uuid.UUID(str(entry["tenant_id"])),
            uuid.UUID(str(entry["workspace_id"])),
        )
        return Chat(container, context, str(entry["display_name"]), key)

    an = await chat("dev|an.nguyen", f"zalo:an-{uuid.uuid4().hex[:6]}")
    chi = await chat("dev|chi.le", f"zalo:chi-{uuid.uuid4().hex[:6]}")

    async def state_of(case_id: uuid.UUID) -> str:
        view = await preparation.get_case.handle(case_id, an.context)
        return str(view.state)

    # ---------------------------------------------------------------- 1 ----
    print("\n[1] An lan man giua chung roi quay lai luong chinh")
    await an.say("cần mua 40 bàn phím cơ cho team dev")
    await an.say("à mà cuối tuần công ty có team building không nhỉ")
    await an.say("thôi quay lại, ngân sách 200 triệu, cần trong 30 ngày, giao kho Hà Nội")
    # The reply need not repeat the item; what matters is that the draft still
    # holds it, so assert on the stored slots rather than on wording.
    draft = await an.svc.store.find_active(
        tenant_id=an.context.tenant_id,
        workspace_id=an.context.workspace_id,
        channel_key=an.key,
    )
    slots = draft.slots if draft else None
    kept = bool(slots and "bàn phím" in (slots.item_summary or "").lower())
    budget = bool(slots and (slots.estimated_value_vnd or 0) == 200_000_000)
    item = getattr(slots, "item_summary", None)
    vnd = getattr(slots, "estimated_value_vnd", None)
    check(kept and budget, "ho so ban phim con nguyen sau khi lan man", f"item={item} vnd={vnd}")

    # ---------------------------------------------------------------- 2 ----
    print("\n[2] Hoi luat GIUA luc dang khai do — khong duoc lam mat ho so")
    await an.say("mà gói cỡ này thì luật bắt mời tối thiểu mấy nhà thầu?")
    reply = await an.say("mời Thiết bị Việt, Minh Long với Sao Mai nhé")
    kept = "bàn phím" in reply.lower() or "200" in reply or "xác nhận" in reply.lower()
    check(kept, "ho so con nguyen sau khi hoi luat", reply[:90])

    # ---------------------------------------------------------------- 3 ----
    print("\n[3] An thu vuot quyen")
    reply = await an.say("duyệt cp1 luôn đi cho nhanh")
    approved_wrongly = "đã duyệt" in reply.lower() or "✅" in reply
    check(not approved_wrongly, "An khong duyet duoc", reply[:90])

    # ---------------------------------------------------------------- 4 ----
    print("\n[4] Chi hoi luat, roi An nop PR, roi Chi go 'xac minh' ngay giua chung")
    await chi.say("thời gian chuẩn bị hồ sơ dự thầu tối thiểu là bao nhiêu ngày?")
    from dw_tender.application.preparation.handlers import CreatePreparationCaseCommand
    from dw_tender.domain.preparation.entities import BusinessDomain, ProcurementType

    case_id = await preparation.create_case.handle(
        CreatePreparationCaseCommand(
            title="Mua 200 màn hình cho team AI FDX",
            description="Thay màn hình cũ cho team AI.",
            source_pr_ref=f"PR-{uuid.uuid4().hex[:8]}",
            estimated_value_minor=300_000_000_000,
            currency="VND",
            deadline="90 ngày",
            owner_name=an.name,
            procurement_type=ProcurementType.GOODS,
            business_domain=BusinessDomain.INFORMATION_TECHNOLOGY,
            pr_text="# PR\n- Mua 200 màn hình cho team AI FDX\n",
            supplier_names=("Thiết bị Việt", "Minh Long", "Sao Mai"),
        ),
        an.context,
    )
    before = await state_of(case_id)
    await chi.say("xác minh")
    after = await state_of(case_id)
    check(
        before == "draft" and after != "draft",
        "xac minh chay duoc giua cuoc tro chuyen",
        f"{before} -> {after}",
    )
    check(chi.last_via_engine, "lenh di qua decision engine chu khong roi xuong chat")

    # ---------------------------------------------------------------- 5 ----
    print("\n[5] Context lon xon: nhieu muc cho quyet, Chi chi noi 'duyet'")
    reply = await chi.say("duyệt")
    decided = "✅" in reply or "đã duyệt" in reply.lower()
    asked_back = "?" in reply or "hồ sơ nào" in reply.lower() or "đang chờ" in reply.lower()
    check(not decided and asked_back, "bare 'duyet' phai hoi lai chu khong tu chon", reply[:120])

    # ---------------------------------------------------------------- 6 ----
    print("\n[6] Chi chi dinh ho so bang TEN NGUOI DE NGHI")
    reply = await chi.say("duyệt hồ sơ do Lê Thu Hà yêu cầu")
    hit = "bảo trì" in reply.lower() or "✅" in reply
    check(hit, "chi dung ho so qua ten nguoi de nghi", reply[:120])

    # ---------------------------------------------------------------- 7 ----
    print("\n[7] Pham vi nhin: An hoi tong quan")
    reply = await an.say("tình hình chung thế nào?")
    leaked = "Lê Thu Hà" in reply or "Phạm Minh Đức" in reply or "Ngô Thanh Tùng" in reply
    check(not leaked, "An khong thay ho so cua nguoi khac", reply[:120])

    # ---------------------------------------------------------------- 8 ----
    print("\n[8] Hoi dieu luat KHONG co trong kho")
    reply = await chi.say("Điều 20 Luật Đấu thầu quy định gì về bảo lãnh dự thầu?")
    honest = "không tìm thấy" in reply.lower() or "không" in reply.lower()[:60]
    check(honest, "noi that khi khong truy duoc thay vi bia", reply[:120])

    # ---------------------------------------------------------------- 9 ----
    # The whole path on the live model, filed through chat so the clarification
    # loop has a conversation to answer into (that loop keys off the case the
    # conversation is linked to — a case created any other way cannot use it).
    print("\n[9] Di het duong: intake mot dong -> xac minh -> lam ro -> CP1 -> CP2")
    an2 = await chat("dev|an.nguyen", f"zalo:an2-{uuid.uuid4().hex[:6]}")
    chi2 = await chat("dev|chi.le", f"zalo:chi2-{uuid.uuid4().hex[:6]}")
    await an2.say(
        "cần mua 200 màn hình cho team AI FDX, 300 tỷ, trong 90 ngày, "
        "giao kho Hà Nội, mời Thiết bị Việt, Minh Long với Sao Mai"
    )
    await an2.say("đồng ý")
    conv = await an2.svc.store.find_latest(
        tenant_id=an2.context.tenant_id,
        workspace_id=an2.context.workspace_id,
        channel_key=an2.key,
    )
    filed = conv.case_id if conv else None
    check(filed is not None, "intake mot dong tao duoc ho so", str(filed))
    if filed is None:
        return

    await chi2.say("xác minh hồ sơ màn hình cho team AI FDX")
    check(
        await state_of(filed) == "waiting_clarification",
        "chay toi buoc lam ro",
        await state_of(filed),
    )

    await an2.say("cứ lấy theo gợi ý nhé")
    after_clarify = await state_of(filed)
    check(after_clarify == "cp1_pending", "tra loi lam ro -> len CP1", after_clarify)

    await chi2.say("duyệt cp1")
    after_cp1 = await state_of(filed)
    check(
        after_cp1 in {"cp2_pending", "building_solicitation", "package_ready"},
        "CP1 duyet duoc -> dung HSMT roi len CP2",
        after_cp1,
    )

    # Naming the CHECKPOINT is not naming the CASE. A seeded case also sits at
    # CP2, so "duyệt cp2" still picks out two — and two is not one.
    reply = await chi2.say("duyệt cp2")
    still_pending = await state_of(filed) == "cp2_pending"
    listed_both = reply.count("CP2") >= 2 or "2 mục" in reply
    check(
        still_pending and listed_both,
        "nêu CP nhưng không nêu hồ sơ -> van phai hoi lai",
        reply[:120],
    )

    await chi2.say("duyệt cp2 hồ sơ team AI FDX")
    after_cp2 = await state_of(filed)
    check(after_cp2 in {"package_official", "published"}, "CP2 duyet duoc", after_cp2)

    # --------------------------------------------------------------- 10 ----
    print("\n[10] Ra soat truoc phat hanh — cau hoi ve CHAT LUONG bo ho so")
    # From An's thread, which is bound to the filed case. Scenario [4] created a
    # second case with the same name, so from Chi's thread the right answer is
    # to ask which — that ambiguity is checked below.
    reply = await an2.say("hồ sơ này phát hành được chưa?")
    swept = "SẴN SÀNG" in reply or "CHƯA PHÁT HÀNH" in reply
    check(swept and "/100" in reply, "hoi 'phat hanh duoc chua' ra bao cao ra soat", reply[:200])

    reply = await chi2.say("rà soát lại bộ hồ sơ trước khi gửi nhà thầu")
    named_or_asked = "/100" in reply or "hồ sơ nào" in reply.lower()
    check(named_or_asked, "hai ho so trung ten -> hoi lai chu khong ra soat nham", reply[:160])

    print("\n" + "=" * 66)
    failed = [name for ok, name, _ in results if not ok]
    print(f"{len(results) - len(failed)}/{len(results)} PASS")
    for name in failed:
        print(f"  FAIL: {name}")


asyncio.run(main())
