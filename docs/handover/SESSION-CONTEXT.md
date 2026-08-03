# Bàn giao ngữ cảnh — DW01 demo (cập nhật 2026-08-03)

File này tồn tại để bất kỳ ai (người hoặc AI assistant) mở repo trên máy mới
nắm được các quyết định và quy ước KHÔNG suy ra được từ code. Đọc kèm:
`CLAUDE.md`, `docs/overview/DW01_BUSINESS_OVERVIEW.md`,
`docs/overview/DW01_TECHNICAL_OVERVIEW.md`, `docs/runbooks/demo-script.md`.

## Quy ước làm việc (standing preferences của chủ repo)

- **Commit message KHÔNG kèm Claude/AI co-author.** Conventional Commits.
- **Secrets chỉ nằm trong `.env`** (đã gitignore, chủ repo tự mang theo):
  Slack `xoxb-`/`xapp-`, DeepSeek API key, Gmail SMTP app password,
  Keycloak/Postgres password. Không bao giờ commit hay in token ra log/chat.
- **Giao tiếp với chủ repo bằng tiếng Việt**, ngắn gọn, đi thẳng vấn đề.
- Sau khi sửa code demo: **build lại docker (khi được yêu cầu), kiểm chứng
  container chạy đúng image mới** (`docker inspect` so với `docker images`),
  và xác minh Slack socket connected trước khi báo xong.

## Triết lý sản phẩm đã chốt (đừng làm ngược lại)

- **"LLM drafts; deterministic code decides"** — model chỉ bóc thông tin và
  soạn câu; ngưỡng tiền, hình thức mua sắm, gate, routing hành động, match
  tên NCC, từ khóa duyệt/từ chối đều là code deterministic + rule pack có
  version (`configs/policies/dw01/procurement_rules_v1.yaml`, theo Phụ lục G
  tài liệu FPT v3.1).
- **Slack để làm — web để chứng kiến.** An/Bình làm việc 100% qua DM với
  "Ngọc"; web (`localhost:3000`) là back office CHỈ ĐỌC, login duy nhất
  `chi` / `demo`. Không thêm nút tạo/duyệt vào web.
- **Ngọc nói như đồng nghiệp** ("mình"), không bao giờ tự nhận là AI/Digital
  Worker. Card Slack: mọi nội dung hiện thẳng (không giấu vào thread),
  hạn chế icon (chỉ ✅❌ trên nút, ⚠️ cảnh báo), thinking hiển thị dạng
  context block chữ xám "_Suy nghĩ_".
- **Trí nhớ chat = slot state trong DB** (`tender.chat_conversations`),
  không phải scrollback Slack. Muốn "Ngọc quên": `bash scripts/demo_reset.sh`
  (+ `scripts/slack_clear_dm.py` để dọn mặt tiền).
- **RAG có răng**: ràng buộc pháp lý (vd thời gian nộp thầu tối thiểu
  Điều 45) do LLM bóc từ passage đã truy, `verified_constraint()` kiểm
  nguyên văn (chống bịa), rồi code áp vào timeline + gate CP2. Corpus seed
  bằng `scripts/seed_knowledge.py`; vectors là dữ liệu dẫn xuất
  (`scripts/knowledge_reindex.py` rebuild được từ Postgres).
- **Human-in-command**: mọi CP do người quyết (nút HOẶC text "duyệt cp1...");
  ngoại lệ duy nhất: gói <10tr + Review Agent OK + profile `autonomous_demo`
  → CP1 tự duyệt có ghi vết, Bình nhận FYI. CP2 duyệt xong = tự phát hành
  RFQ qua email, không ai bấm thêm.

## Nguồn ngữ cảnh gốc

Hai tài liệu chủ repo cung cấp (bản PDF không nằm trong repo — chủ repo giữ):

1. _Phương pháp tiếp cận DW Mua sắm — Operating Cell v3.1_ (FPT) — quy trình
   18 bước, CP1–CP4, PV levels, CASAN, Phụ lục G ngưỡng giá trị.
2. _Mô tả Bộ phận Mua sắm_ — vai An/Bình/Chi, điểm đau P1–P5.

Nội dung đã được distill vào rule pack + 2 file overview; nếu cần chi tiết
nguyên bản thì xin lại PDF từ chủ repo.

## Trạng thái & việc treo (tính đến 2026-08-03)

- Demo DW01 chạy đủ: intake chat → clarify → RAG+ràng buộc → CP1 → CP2 →
  auto-publish email → bàn tiếp nhận HSDT của Bình (nút/text + file thật) →
  CP4 → bàn giao DW02. CI đã xanh local cả 4 job static.
- Tech debt đã thừa nhận với chủ repo: text-decision routing đang nằm trong
  `apps/api/src/dw_api/channels/slack.py` (adapter) — nơi đúng là một
  `DecisionCommandService` channel-agnostic; DW02 chưa build; eval dataset
  đầy đủ + Langfuse + RLS test cho `chat_conversations` còn thiếu.
- Test e2e `test_dw01_upload_only_cp1_to_cp4` có assertion thứ tự
  notification cũ (verify-intake giờ auto-run nên `intake.approved` không
  còn là notification cuối) — chủ repo đã thấy và tự quyết cách xử lý.
