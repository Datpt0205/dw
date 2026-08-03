"""Seed the demo knowledge corpus with realistic regulation documents.

Replaces the one-line law stubs left behind by earlier test runs with a proper
trích lược of Luật Đấu thầu (including Điều 45 — thời gian chuẩn bị hồ sơ dự
thầu, which the DW01 approach node extracts as a hard constraint) plus the
internal procurement quy chế. Content lives HERE (single seed source); ingest
goes through the real KnowledgeGateway — structure-aware chunking, BGE-M3
embedding and Qdrant upsert, nothing is faked.

Run INSIDE the api container:

    docker compose --env-file .env -f infra/compose/docker-compose.yml \
        exec -T api python - < scripts/seed_knowledge.py

Then rebuild the vector collection so vectors of purged docs disappear:

    docker compose --env-file .env -f infra/compose/docker-compose.yml \
        exec -T api python - < scripts/knowledge_reindex.py
"""

from __future__ import annotations

import asyncio
import uuid

import sqlalchemy as sa

# Same deterministic identity scheme as scripts/seed_demo.py — the platform
# tables are RLS-guarded for the app role, so we derive ids instead of reading.
SEED_NAMESPACE = uuid.UUID("6f0f6f1e-9f6a-4f65-9a1c-000000000d10")


def sid(kind: str, key: str) -> uuid.UUID:
    return uuid.uuid5(SEED_NAMESPACE, f"{kind}:{key}")


LUAT_DAU_THAU = """\
# Luật Đấu thầu — trích lục phục vụ mua sắm (bản trích lược demo, \
cấu trúc theo Luật Đấu thầu số 22/2023/QH15)

## Điều 20. Chỉ định thầu
Chỉ định thầu được áp dụng đối với gói thầu có giá trị nhỏ trong hạn mức theo \
quy định của Chính phủ; gói thầu cấp bách cần triển khai ngay để khắc phục sự \
cố; hoặc gói thầu chỉ có một nhà cung cấp duy nhất đáp ứng yêu cầu kỹ thuật. \
Đơn vị áp dụng chỉ định thầu phải bảo đảm nhà thầu được chỉ định có đủ năng \
lực, kinh nghiệm và giá đề nghị hợp lý.

## Điều 21. Chào hàng cạnh tranh
Chào hàng cạnh tranh được áp dụng đối với gói thầu mua sắm hàng hoá thông \
dụng, sẵn có trên thị trường với đặc tính kỹ thuật được tiêu chuẩn hoá và \
tương đương nhau về chất lượng. Bên mời thầu phải gửi yêu cầu báo giá tới tối \
thiểu ba nhà cung cấp và công khai tiêu chí so sánh giá.

## Điều 22. Đấu thầu rộng rãi
Đấu thầu rộng rãi là hình thức lựa chọn nhà thầu trong đó không hạn chế số \
lượng nhà thầu tham dự. Đấu thầu rộng rãi được áp dụng cho mọi gói thầu, trừ \
trường hợp được phép áp dụng hình thức khác theo quy định của Luật này. Hồ sơ \
mời thầu phải công khai tiêu chuẩn đánh giá và không được nêu điều kiện nhằm \
hạn chế sự tham gia của nhà thầu hoặc tạo lợi thế cho một nhà thầu cụ thể.

## Điều 43. Bảo đảm dự thầu
Nhà thầu phải thực hiện biện pháp bảo đảm dự thầu trước thời điểm đóng thầu \
theo yêu cầu của hồ sơ mời thầu. Giá trị bảo đảm dự thầu được quy định trong \
khoảng từ 1% đến 3% giá gói thầu.

## Điều 45. Thời gian tổ chức lựa chọn nhà thầu
1. Thời gian chuẩn bị hồ sơ dự thầu đối với đấu thầu rộng rãi trong nước tối \
thiểu là 18 ngày, kể từ ngày đầu tiên hồ sơ mời thầu được phát hành đến ngày \
có thời điểm đóng thầu; đối với đấu thầu quốc tế tối thiểu là 35 ngày.
2. Đối với chào hàng cạnh tranh, thời gian chuẩn bị hồ sơ dự thầu tối thiểu \
là 05 ngày làm việc, kể từ ngày đầu tiên hồ sơ yêu cầu được phát hành.
3. Việc sửa đổi hồ sơ mời thầu sau khi phát hành phải được thông báo tới mọi \
nhà thầu đã nhận hồ sơ tối thiểu 10 ngày trước thời điểm đóng thầu; trường \
hợp không bảo đảm thời gian này, bên mời thầu phải gia hạn thời điểm đóng \
thầu tương ứng.
"""

QUY_CHE_NOI_BO = """\
# Quy chế mua sắm nội bộ Công ty Alpha (01-QT/MH — trích lược demo)

## Mục 1. Hình thức mua sắm theo giá trị gói (Phụ lục G)
Gói dưới 10.000.000 đồng: mua sắm trực tiếp, tối thiểu 01 nhà cung cấp. Gói \
từ 10.000.000 đồng đến 5.000.000.000 đồng: chào giá cạnh tranh, tối thiểu 03 \
nhà cung cấp. Gói trên 5.000.000.000 đồng: tổ chức đấu thầu, tối thiểu 03 nhà \
thầu tham dự.

## Mục 2. Hạn mức phê duyệt
Trưởng phòng phê duyệt tới 200.000.000 đồng; Giám đốc khối tới 1.000.000.000 \
đồng; trên mức này thuộc thẩm quyền Tổng Giám đốc hoặc người được ủy quyền \
bằng văn bản. Người lập hồ sơ không được đồng thời là người phê duyệt hồ sơ \
đó ở bất kỳ điểm kiểm soát nào.

## Mục 3. Nghĩa vụ rà soát bổ sung
Hợp đồng trên 100.000.000 đồng phải được pháp chế xem xét trước khi phát \
hành. Hàng hoá chuyên môn trên 300.000.000 đồng cần ý kiến Trưởng bộ phận mua \
sắm. Gói tài sản cố định hoặc CNTT trên 5.000.000.000 đồng phải lập bảng Tổng \
chi phí sở hữu (TCO) theo biểu mẫu 01.6-BM trước khi trình duyệt phương án.
"""

# (title, domain, scope, content) — deterministic doc identity comes from
# tenant/workspace/domain/title/version inside the gateway (idempotent re-run).
DOCUMENTS = [
    ("Luật Đấu thầu — trích lục", "legal", "global", LUAT_DAU_THAU),
    ("Quy chế mua sắm nội bộ Alpha", "policy", "tenant", QUY_CHE_NOI_BO),
]

# Test relics: one-line stubs with hash suffixes ("Luat DT 218dfa", ...).
JUNK_TITLE_SQL = r"title ~ ' [0-9a-f]{6}$' or title like '%(live PDF)%'"


async def main() -> None:
    from dw_api import bootstrap
    from dw_knowledge.gateway import IngestDocumentCommand
    from dw_platform.application.access_context import AccessContext

    container = bootstrap.build_container()
    gateway = container.knowledge_gateway
    assert gateway is not None, "knowledge gateway is not wired"

    context = AccessContext(
        tenant_id=sid("tenant", "tenant-alpha"),
        workspace_id=sid("workspace", "tenant-alpha:main"),
        principal_id=sid("user", "dev|chi.le"),
        roles=frozenset({"admin"}),
        scopes=frozenset({"knowledge.read", "knowledge.write"}),
        clearance="internal",
        plan_id="professional",
    )

    # 1) Purge stub documents left behind by old test runs (per-tenant RLS GUC).
    async with gateway.session_factory() as session, session.begin():
        # RLS hides tenant-scoped rows without the GUC — scope to the demo
        # tenant first (global-scope rows are visible regardless).
        await session.execute(
            sa.text("select set_config('app.tenant_id', :t, true)"),
            {"t": str(context.tenant_id)},
        )
        junk = (
            await session.execute(
                sa.text(
                    f"select id, tenant_id, title from knowledge.documents where {JUNK_TITLE_SQL}"
                )
            )
        ).all()
        for doc in junk:
            await session.execute(
                sa.text("select set_config('app.tenant_id', :t, true)"),
                {"t": str(doc.tenant_id)},
            )
            await session.execute(
                sa.text("delete from knowledge.chunks where document_id = :d"),
                {"d": doc.id},
            )
            await session.execute(
                sa.text("delete from knowledge.documents where id = :d"), {"d": doc.id}
            )
            print("purged:", doc.title)

    # 2) Ingest the real corpus through the gateway (chunk + embed + upsert).
    for title, domain, scope, content in DOCUMENTS:
        result = await gateway.ingest_document(
            IngestDocumentCommand(
                title=title,
                content=content,
                domain=domain,
                classification="internal",
                source_version="2026-08",
                content_type="text/markdown",
                scope=scope,
            ),
            context,
        )
        print(f"ingested: {title} ({domain}/{scope}) -> {result.chunk_count} chunks")

    print("done — run knowledge_reindex.py to drop stale vectors of purged docs")


asyncio.run(main())
