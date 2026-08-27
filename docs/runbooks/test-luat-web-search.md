# Kịch bản test — tra luật bằng web search + cảnh báo luật đổi

Bạn thao tác trên **Zalo**; các lệnh SQL ở đây chỉ để **kiểm chứng** kết quả, không
phải để điều khiển luồng.

Điểm khác so với kịch bản demo cũ: mọi câu hỏi tri thức trên chat giờ tra **cả corpus
lẫn Google (serper.dev)** rồi trộn kết quả, và câu trả lời phải **dẫn URL** cho phần lấy
từ mạng. Riêng khi soạn HSMT, câu hỏi về luật (`domain=legal`) đi thẳng ra web.

Cách nhận biết ngay trên Zalo: đoạn nào lấy từ mạng thì câu trả lời ghi
`(tên nguồn — https://…)`; tài liệu nội bộ vẫn ghi `(tên tài liệu, phiên bản X)`.

---

## 0a. Lấy khoá cho chuỗi provider

Chuỗi chỉ dài bằng số khoá bạn thực sự có. **Một tầng vẫn chạy đúng** — chỉ là không
còn ai đỡ khi tầng đó hết lượt. Thiếu hết cả bốn thì hệ thống vẫn không sập: nó rơi về
corpus đã ingest và in cảnh báo lên thẻ duyệt.

Hạn mức dưới đây **đo ngày 2026-08-25**. Thị trường này đổi nhanh — hai trong bốn dòng
đã đổi trong sáu tháng — nên nếu bạn đọc cái này sau vài tháng, hãy tra lại trước khi tin.

| Provider       | Free (đo 25/08/2026)           | Thẻ?      | Tái tạo    | Lấy được?       |
| -------------- | ------------------------------ | --------- | ---------- | --------------- |
| **serper**     | 2.500 lượt, hạn 6 tháng        | Không     | ❌ một lần | ✅              |
| **tavily**     | 1.000 credit/tháng             | **Không** | ✅ tháng   | ✅              |
| **brave**      | $5 tín dụng/tháng ≈ 1.000 lượt | **Có**    | ✅ tháng   | ✅              |
| **google_cse** | 100 lượt/ngày                  | Có        | ✅ ngày    | ❌ **đã đóng**  |
| duckduckgo     | —                              | Không     | —          | ⚠️ không có API |

### Tavily — lấy cái này trước

Đây là tầng tự tái tạo **duy nhất** lấy được mà không phải khai thẻ, và cũng là cửa duy
nhất trong chuỗi có cơ đọc được nguồn render bằng JavaScript (nó trả sẵn nội dung trang).

1. Đăng ký tại **<https://tavily.com>** — không cần thẻ
2. Vào mục **API Keys**, copy khoá dạng `tvly-…`
3. Dán vào `.env`:

```bash
TAVILY_API_KEY=tvly-...
```

Lưu ý về credit: `basic` tốn 1 credit/lượt, `advanced` tốn 2. Config để `basic`
(`search.tavily_search_depth`) vì phần Tavily bóc đoạn hộ ta bị vứt đi — xem comment
trong `configs/knowledge/legal_sources@1.1.0.yaml`.

### Brave — cần thẻ, tuỳ bạn

Brave **bỏ free tier từ 02/2026**. Giờ là $5 tín dụng mỗi tháng, và trang của họ ghi rõ
thẻ là _"an anti-fraud measure"_ và _"will not be charged"_ với gói free — nhưng vẫn là
thẻ, nên đây là lựa chọn của bạn chứ không phải bước bắt buộc.

Vẫn đáng có nếu bạn muốn chuỗi thật sự dự phòng: Brave chạy **chỉ mục crawl riêng**,
không bán lại Google. Một chuỗi chỉ diễn đạt lại cùng một chỉ mục sẽ trả về cùng một câu
trả lời sai.

1. **<https://brave.com/search/api/>** → chọn gói **Free**
2. Khai thẻ (không bị trừ ở gói free)
3. Copy **Subscription Token** → `.env`:

```bash
BRAVE_API_KEY=BSA...
```

### Google CSE — bỏ qua, không đăng ký được nữa

Banner trên chính trang tài liệu của Google:

> _"The Custom Search JSON API is closed to new customers."_

Và API **ngừng hẳn 01/01/2027**. Để trống `GOOGLE_CSE_API_KEY` và `GOOGLE_CSE_CX`, đừng
mất buổi chiều đi tìm.

Ngoại lệ duy nhất: nếu tổ chức bạn **đã** là khách hàng cũ thì hạn mức 100 lượt/ngày rất
hợp làm chân đỡ (tự hồi mỗi sáng, không như hạn mức tháng cạn giữa chừng). Khi đó bật
`{ name: google_cse, enabled: true }` trong config và điền cả hai biến. Adapter giữ lại
chính vì trường hợp này.

### Sau khi dán khoá

```bash
$DC --profile full up -d --force-recreate api
docker logs dw-api-1 2>&1 | grep -E "legal retrieval via|chưa cấu hình khoá"
```

---

## 0. Xác nhận đang ở chế độ web

```bash
docker exec dw-api-1 python -c "
from dw_api import bootstrap
c = bootstrap.build_container()
print('nguồn luật :', c.settings.legal_source)
print('gateway    :', type(c.legal_gateway).__name__)
print('model      :', c.settings.model_profile)"
```

Phải thấy:

```
nguồn luật : web
gateway    : LegalSourceRouter      ← nếu là KnowledgeGateway thì đang chạy corpus cũ
model      : openai
```

`LegalSourceRouter` mới là chế độ mới. Ra `KnowledgeGateway` nghĩa là **không
provider nào có khoá**, hoặc `DW_LEGAL_SOURCE` chưa phải `web` — hệ thống **cố ý**
rơi về corpus thay vì chạy không có căn cứ nào.

Xem chuỗi provider đã dựng được mấy tầng:

```bash
docker logs dw-api-1 2>&1 | grep -E "legal retrieval via|bỏ qua .* chưa cấu hình khoá"
```

Phải thấy một dòng kiểu:

```
legal retrieval via web search (chuỗi: serper → tavily → brave | 7 nguồn tin cậy | config 1.1.0)
```

Provider nào thiếu khoá sẽ có dòng `web search: bỏ qua <tên> — chưa cấu hình khoá`
ngay trước đó. **Đó là hành vi đúng**, không phải lỗi: chuỗi chỉ dài bằng số khoá
bạn thực sự có. Một tầng vẫn chạy được, chỉ là không còn ai đỡ khi tầng đó hết lượt.

Đặt sẵn biến tắt cho các lệnh phía dưới:

```bash
DC="docker compose --env-file .env -f infra/compose/docker-compose.yml"
```

Reset trước khi bắt đầu:

```bash
bash scripts/demo_reset.sh && bash scripts/seed_demo_cases.sh
```

---

## 1. Hỏi luật trực tiếp — 3 câu

Nhắn từ tài khoản **AN**. Đây là bài kiểm chính: cả ba câu phải trả lời bằng con số
**trích từ văn bản**, và phải nói rõ chưa chốt được mốc nào khi chưa biết hình thức.

> **Chat trộn hai nguồn.** Một câu trả lời có thể vừa dẫn luật từ mạng vừa dẫn quy chế
> nội bộ từ corpus — đó là đúng, không phải nhầm lẫn. Hai loại căn cứ khác nhau và câu
> trả lời phải phân biệt được.

**1.1**

```
gói thầu rộng rãi trong nước thì luật cho nhà thầu bao nhiêu ngày chuẩn bị hồ sơ?
```

Kỳ vọng: **18 ngày** (đấu thầu trong nước), có nêu **35 ngày** cho quốc tế, kèm đoạn
trích nguyên văn **và URL bấm được**. Mất khoảng **8–12 giây** — chậm hơn trước vì phải
tra mạng và tải trang.

Không thấy URL nào trong câu trả lời = phần web không đóng góp được đoạn nào; xem log ở
bước tiếp theo để biết vì sao.

**1.2**

```
chào hàng cạnh tranh thì bao nhiêu ngày?
```

Kỳ vọng: **05 ngày làm việc**. Đây là câu bẫy: nếu bot trả 18 ngày thì nó đang đọc
nhầm điều khoản.

**1.3**

```
điều nào của luật quy định chuyện đó?
```

Kỳ vọng: nêu **Điều 45**. Nếu bịa ra điều khác thì phần trích dẫn đang có vấn đề.

### Kiểm chứng ngay: đã tra những web nào?

```bash
docker logs dw-api-1 2>&1 | grep "web law" | tail -5
```

Mỗi truy vấn một dòng, nêu đủ: đã tra web nào, trang nào đọc được, mỗi trang cho mấy đoạn:

```
web law: "gói thầu rộng rãi trong nước cho nhà thầu bao nhiêu ngày ch…"
  → 10 kết quả, 4 qua allowlist
  [luatvietnam.vn ✗0 đoạn, luatvietnam.vn ✗0 đoạn, luatvietnam.vn ✓1 đoạn]
  1 đoạn dùng được, 3.4s
```

`✗0 đoạn` = tải được trang nhưng không cắt ra đoạn nào chứa mốc ngày.
`✗không đọc được` = trang chặn hoặc lỗi mạng.

### Kiểm chứng sâu: đúng là từ web chứ không phải corpus?

```bash
$DC exec -T postgres psql -U dw_admin -d dw -c "
select c.title,
       jsonb_array_elements(a.content_json->'legal_basis')->>'source_uri' as url,
       jsonb_array_elements(a.content_json->'legal_basis')->>'source_version' as nguon
from tender.preparation_artifacts a
join tender.preparation_cases c on c.id = a.case_id
where a.artifact_type = 'procurement_approach'
order by a.created_at desc limit 6"
```

| Cột                                      | Nghĩa là                                        |
| ---------------------------------------- | ----------------------------------------------- |
| `url` có giá trị, `nguon` bắt đầu `web:` | ✅ lấy từ mạng lúc soạn hồ sơ                   |
| `url` rỗng, `nguon` là `2026-08`         | tài liệu nội bộ trong corpus (đúng với quy chế) |

_(Bảng này rỗng cho tới khi bạn tạo một hồ sơ ở mục 2 — hỏi luật đơn thuần chưa sinh
artifact.)_

---

## 2. Tạo hồ sơ để lấy căn cứ vào artifact

Vẫn từ **AN**, đúng như kịch bản demo:

```
Cần mua 200 màn hình cho team AI FDX, 300 tỷ, trong 90 ngày, giao kho Hà Nội, mời Thiết bị Việt, Minh Long với Sao Mai
```

```
đồng ý
```

Rồi từ **CHI**:

```
xác minh hồ sơ màn hình cho team AI FDX
```

Từ **AN** (chờ khoảng 25s sau câu trên):

```
cứ lấy theo gợi ý nhé
```

Tới đây hồ sơ đã qua bước soạn phương án — tức là đã tra luật và ghi căn cứ.

### Xem con số đã bóc ra được

```bash
$DC exec -T postgres psql -U dw_admin -d dw -c "
select c.title,
       a.content_json->'legal_constraints'->'extracted'->>'min_bid_preparation_days' as so_ngay,
       a.content_json->'legal_constraints'->'extracted'->>'article_ref' as dieu_khoan,
       a.content_json->'legal_constraints'->>'applied_window_days' as ap_dung,
       a.content_json->>'grounding_status' as trang_thai
from tender.preparation_artifacts a
join tender.preparation_cases c on c.id = a.case_id
where a.artifact_type='procurement_approach' order by a.created_at desc limit 1"
```

Kỳ vọng: `so_ngay = 18`, `dieu_khoan` có "Điều 45", `trang_thai = grounded`.

**`so_ngay` rỗng không phải lỗi hệ thống.** Nghĩa là model chép ra một câu mà
`verified_constraint()` không tìm thấy nguyên văn trong đoạn đã truy hồi, nên con số bị
vứt và mốc mặc định tất định (22 ngày cho đấu thầu rộng rãi) được dùng. Đó là hàng rào
chống bịa làm đúng việc — nhưng nếu lặp lại nhiều lần thì chất lượng đoạn truy hồi có
vấn đề, đáng báo lại.

**`ap_dung` luôn ≥ `so_ngay`.** Luật chỉ kéo dài được thời hạn, không rút ngắn.

---

## 3. Cảnh báo khi luật đổi

Watcher chạy **mỗi 60 giây** (`DW_LAW_WATCH_INTERVAL_SECONDS=60` trong `.env`; mặc định
thật là 6 giờ).

Không đợi được luật thật đổi, nên ta **sửa mốc đã ghi trong hồ sơ** cho lệch với thứ
mạng đang nói — hiệu ứng giống hệt luật vừa thay đổi.

**3.1 — Đổi con số đã lưu từ 18 xuống 7:**

```bash
$DC exec -T postgres psql -U dw_admin -d dw -c "
update tender.preparation_artifacts
set content_json = jsonb_set(content_json,
      '{legal_constraints,extracted,min_bid_preparation_days}', '7')
where id = (select id from tender.preparation_artifacts
            where artifact_type='procurement_approach'
            order by created_at desc limit 1)
returning case_id"
```

**3.2 — Chờ khoảng 90 giây, rồi xem cảnh báo đã vào hàng đợi chưa:**

```bash
$DC exec -T postgres psql -U dw_admin -d dw -c "
select status, payload->>'title' as tieu_de,
       payload->>'before' as truoc, payload->>'after' as sau,
       payload->>'article_ref' as dieu_khoan
from tender.approval_notification_jobs
where event_type = 'law.change_detected'"
```

Kỳ vọng: đúng **một** dòng, `truoc = 7`, `sau = 18`.

**3.3 — Xem thẻ trên Zalo.** Tài khoản duyệt (**CHI**) nhận được thẻ nêu mốc cũ, mốc mới,
đoạn trích và câu:

> Phiếu duyệt vẫn còn hiệu lực — đây là thông tin để bạn quyết.

**Phiếu duyệt KHÔNG bị thu hồi.** Đây là điểm thiết kế cố ý: một kết quả tìm kiếm sai
không được phép tự phá một hồ sơ đang chạy. Muốn áp mốc mới thì người duyệt tự sửa hồ sơ,
lúc đó cơ chế cũ mới thu hồi phiếu và chạy lại toàn bộ phép kiểm.

**3.4 — Chờ thêm 2-3 phút nữa rồi chạy lại query 3.2.** Vẫn phải là **một** dòng.
Watcher quét lại mỗi phút nhưng cùng một thay đổi chỉ báo một lần.

**3.5 — Kiểm tra vết kiểm toán.** Mỗi lượt quét đều ghi lại, kể cả lượt không có gì đổi:

```bash
$DC exec -T postgres psql -U dw_admin -d dw -c "
select a.created_at, a.content_json->>'changed' as co_doi,
       a.content_json->'sources_now_say'->>'min_bid_preparation_days' as mang_noi
from tender.preparation_artifacts a
where a.artifact_type='law_review' order by a.created_at desc limit 5"
```

---

## 3b. Chuỗi dự phòng — thử làm hỏng tầng đầu

Đây là phần đáng test nhất, vì nó là lý do tồn tại của cả tính năng: khi Serper hết
credit nó trả 403, `_cite()` nuốt lỗi theo thiết kế, và hồ sơ được soạn với **mốc mặc
định, không một trích dẫn nào** — không lỗi, không dấu vết. Chuỗi tồn tại để chuyện đó
không xảy ra lặng lẽ.

**Bước 1 — làm hỏng tầng đầu.** Đổi `SERPER_API_KEY` trong `.env` thành chuỗi rác:

```bash
sed -i 's/^SERPER_API_KEY=.*/SERPER_API_KEY=sai-khoa-co-y/' .env
$DC --profile full up -d --force-recreate api
```

**Bước 2 — hỏi lại câu ở mục 1**, rồi đọc log:

```bash
docker logs dw-api-1 2>&1 | grep -E "web search:|web law:" | tail -5
```

Phải thấy đúng ba điều (`tavily` là tầng #2, xem mục 0a):

```
WARNING web search: serper hết lượt, nghỉ 360 phút — serper: hết lượt hoặc key bị từ chối
INFO    web search: dùng tavily (bỏ qua: serper hết lượt)
INFO    web law: "gói thầu rộng rãi…" qua tavily → 4 qua allowlist […] 1 đoạn dùng được, 3.1s
```

Và **câu trả lời trên Zalo vẫn đúng, vẫn dẫn nguồn**. Người dùng không thấy gì khác.

**Bước 3 — hỏi thêm lần nữa.** Lần này log **không được** có dòng nào về `serper`
nữa: nó đang trong cooldown 6 tiếng, và hỏi lại chỉ tốn thêm một lượt để nhận đúng
câu trả lời cũ.

**Bước 4 — làm hỏng hết.** Xoá giá trị của cả bốn khoá rồi recreate. Bây giờ:

```
WARNING web law: không tra được nguồn trực tuyến nào — trả lời bằng corpus đã ingest (căn cứ có thể cũ)
```

Câu trả lời **vẫn có** (lấy từ corpus), nhưng nếu bạn tạo hồ sơ ở bước này thì thẻ CP1
phải có thêm dòng:

> 📎 Căn cứ pháp lý lấy từ kho đã lưu trong hệ thống, không phải tra trực tuyến tại
> thời điểm này — hãy đối chiếu hiệu lực trước khi duyệt.

Dòng đó là điểm mấu chốt. Không có nó thì "luật hôm nay" và "luật năm ngoái" trông
giống hệt nhau trên thẻ duyệt.

**Bước 5 — trả khoá về như cũ** và recreate lại `api`.

---

## 4. Những gì KHÔNG được đổi

Ba câu này phải hành xử y như trước — nếu khác thì có hồi quy:

**4.1** Hỏi quy chế nội bộ (không có trên mạng, phải đọc từ Qdrant):

```
hạn mức nào thì phải qua đấu thầu theo quy chế công ty?
```

Kỳ vọng: **trên 5 tỷ**, tối thiểu 03 nhà thầu — trích _Quy chế mua sắm nội bộ Alpha_.

**4.2** Tiền đề sai — phải sửa lại chứ không hùa theo:

```
Điều 20 Luật Đấu thầu quy định gì về bảo lãnh dự thầu?
```

Kỳ vọng: nói rõ Điều 20 là về **chỉ định thầu**, không phải bảo lãnh dự thầu.

**4.3** Vượt quyền — vẫn phải bị chặn. Từ **AN**:

```
duyệt cp1 luôn đi cho nhanh
```

---

## 5. Khi có gì đó không ổn

| Hiện tượng                            | Xem ở đâu                                                                                  |
| ------------------------------------- | ------------------------------------------------------------------------------------------ |
| Trả lời luật chung chung, không có số | `grounding_status` ở query mục 2. `not_available` = không truy được căn cứ nào             |
| Chậm hơn 20s mỗi câu hỏi luật         | `max_pages_per_query` trong `configs/knowledge/legal_sources@1.0.0.yaml` (đang là 3)       |
| Nghi hết credit Serper                | `$DC logs api \| grep -i "credits may be exhausted"`                                       |
| Không thấy cảnh báo luật đổi          | `docker logs dw-api-1 \| grep "law watch"` — giờ hiện mỗi 60s, kèm lý do bỏ qua từng hồ sơ |
| Muốn xem đã tra web nào               | `docker logs dw-api-1 \| grep "web law"`                                                   |
| Log quá nhiều                         | `DW_LOG_LEVEL=WARNING` trong `.env`                                                        |
| Muốn tắt hẳn tính năng                | `DW_LEGAL_SOURCE=qdrant` trong `.env` rồi `--force-recreate api`                           |

Log mức INFO **đã được bật** (`DW_LOG_LEVEL=INFO`, mặc định). Lúc khởi động phải thấy:

```
dw_api.bootstrap INFO legal retrieval via web search (sources=7, version=1.0.0)
dw_api.law_watch INFO law watch every 60s as dev|binh.tran
dw_api.channels.zalo INFO zalo front office polling started
```

`httpx` bị hạ riêng xuống WARNING: Zalo long-poll vài lần mỗi giây và bot token nằm
trong URL, để INFO thì vừa ngập log vừa ghi token ra file.

---

## Số đo tham chiếu (2026-08-24, model `gpt-5.6-luna`)

| Bước                                   | Thời gian |
| -------------------------------------- | --------- |
| Serper search + tải 3 trang + cắt đoạn | ~3,6s     |
| Model chép số ra khỏi đoạn             | ~4,3s     |
| **Cộng thêm vào node soạn phương án**  | **~8s**   |

Chuỗi đầy đủ đã chạy thật: web → allowlist → tải trang → cắt đoạn → model chép →
`verified_constraint` **đạt** → 18 ngày, Điều 45 khoản 1 điểm b.

**Nguồn — đo lại ngày 2026-08-24, có sửa một khẳng định sai trước đó:**

| Nguồn                | Trạng thái                                                                                                                                                                                                                                                                                                                     |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `luatvietnam.vn`     | ✅ nguồn duy nhất mang **toàn văn** điều khoản (~200k ký tự) — thực tế đang chạy trên nó                                                                                                                                                                                                                                       |
| `vanban.chinhphu.vn` | phục vụ HTML tĩnh đọc được bình thường. **Không phải render JS** như tôi viết nhầm ở bản trước — con số "48 ký tự" là do lỗi trong bộ bóc chữ của chính hệ thống (loại nhầm thẻ `<form>`, mà ASP.NET bọc cả trang trong đó). Đã sửa. Chỉ còn hạn chế thật: URL Google trả về là trang **mục lục**, văn bản nằm ở file đính kèm |
| `vbpl.vn`            | ❌ **đã bỏ** khỏi allowlist — render JS thật (56KB HTML không có lấy một chữ "đấu thầu"), Serper `/scrape` cũng trả 500                                                                                                                                                                                                        |
| `thuvienphapluat.vn` | ❌ **đã bỏ** — 403 cho mọi request, kể cả khi khai User-Agent trình duyệt                                                                                                                                                                                                                                                      |

Lý do đầy đủ ghi trong `configs/knowledge/legal_sources@1.0.0.yaml`.
