# Threat Model — Digital Worker Platform (POC)

Phương pháp: STRIDE trên từng trust boundary. Mỗi mitigation trỏ đến code/test
thật đang cưỡng chế nó — mitigation không có test coi như không tồn tại.

## Trust boundaries

```
[Browser] --(1)--> [Next.js web] --(2)--> [FastAPI API] --(3)--> [PostgreSQL]
                                              |--(4)--> [Qdrant]
                                              |--(5)--> [MinIO]
                                              |--(6)--> [LLM provider (ngoài)]
                                              |--(7)--> [Task connector (ngoài)]
[Keycloak/DevToken] --(8)--> API (xác thực)
[Transcript/RFQ upload] --(9)--> workflow (dữ liệu KHÔNG tin cậy)
[Upload tài liệu] --(10)--> API POST /knowledge/documents --> MinIO + hàng đợi
                            ingest_jobs --> worker parser (Docling/OCR, dữ liệu
                            KHÔNG tin cậy) --> chunk/embed/index Qdrant
```

> Ranh giới tin cậy mới (async ingest): file người dùng tải lên là **dữ liệu không
> tin cậy** và bị **parse ngoài request** trong worker (Docling/OCR). Bề mặt tấn công:
> file độc hại (decompression bomb, XXE/định dạng lỗi, tiêu hao tài nguyên OCR). Giảm
> thiểu: giới hạn kích thước upload ở API, parser chạy trong worker cách ly + timeout,
> `ingest_jobs` mang `tenant_id` (RLS) nên không rò rỉ chéo tenant, và scope `global`
> chỉ platform_admin mới ghi được.

## S — Spoofing

| Đe dọa                                     | Mitigation                                                                                                                                               | Cưỡng chế tại                                                                        |
| ------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| Giả mạo người dùng qua token tự chế        | Token verify bằng HS256 secret ≥32 ký tự (dev) hoặc RS256/JWKS Keycloak (oidc); AccessContext chỉ dựng từ token đã verify + xác nhận membership trong DB | `dw_platform/adapters/identity/*`, `DbAccessContextFactory`; test `test_me_endpoint` |
| Tự nhận tenant khác qua header X-Tenant-Id | Header chỉ là _yêu cầu_; membership lookup chạy với RLS của chính tenant được yêu cầu → không phải member = 0 rows = 403                                 | `membership_lookup.py`; E2E cross-tenant 403/404                                     |
| Dev auth mode lọt vào production           | `validate_for_profile()` fail-fast: profile production cấm auth_mode=dev và cấm mock model                                                               | `settings.py` (ADR-012, ADR-013)                                                     |

## T — Tampering

| Đe dọa                                                  | Mitigation                                                                                                                                                                              | Cưỡng chế tại                                                             |
| ------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| Prompt injection trong transcript/RFQ điều khiển worker | Nội dung không tin cậy bị giam trong block `<transcript>`/`<rfq>`; system prompt versioned tuyên bố bỏ qua chỉ thị bên trong; mọi side effect vẫn phải qua approval bất kể model nói gì | prompt bundles; eval case `*-sec-prompt-injection`; `requires_approval()` |
| Model bịa điểm số/trích dẫn                             | LLM chỉ đề xuất; `ScoringEngine` quyết định (mandatory không bằng chứng = fail closed); quote phải locate nguyên văn trong tài liệu nguồn mới thành evidence                            | `scoring_engine.py`, `evidence_locator.py`; golden tests + eval cases     |
| Sửa audit trail                                         | Bảng audit/decisions/tool_executions bị REVOKE UPDATE/DELETE với role `dw_app`                                                                                                          | migration 0001; integration test append-only                              |
| Giả release manifest                                    | Manifest content-addressed (sha256); history immutable, collision = lỗi; `--check` chạy trong CI                                                                                        | `release_manifest.py`; unit test                                          |

## R — Repudiation

| Đe dọa                          | Mitigation                                                                                                                                                            | Cưỡng chế tại                              |
| ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------ |
| Chối đã phê duyệt / đã dispatch | ApprovalRequest decide-once (version bump, quyết định thứ hai = conflict); audit event cho mọi run/tool/approval kèm actor + trace_id; run gắn `release_manifest_ref` | `approval.py` domain; timeline E2E asserts |

## I — Information Disclosure

| Đe dọa                                          | Mitigation                                                                                                                                              | Cưỡng chế tại                                                    |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| Đọc dữ liệu tenant khác qua SQL                 | RLS ENABLE+FORCE trên mọi bảng tenant; `dw_app` NOBYPASSRLS; tenant context SET LOCAL mỗi transaction                                                   | migrations + `uow.py`; RLS integration tests                     |
| Đọc vector tenant khác qua Qdrant               | `SearchQuery` cấm trường tenant (`extra="forbid"`); filter chỉ được dựng trong `build_trusted_filter()` từ AccessContext; clearance ceiling fail-closed | `dw_knowledge/gateway.py`; Qdrant isolation test + eval case     |
| Secret/PII lọt vào log/trace                    | Redaction key-pattern + Bearer scrub trước khi attribute rời process; telemetry chỉ chứa safe identifier, không chứa prompt content                     | `dw_observability/redaction.py`, `safe_attributes()`; unit tests |
| SSRF qua base_url provider (đọc metadata cloud) | `ensure_allowed_outbound_url`: chỉ http(s), cấm credentials nhúng, cấm private/loopback/link-local trừ khi dev hoặc allowlist                           | `dw_kernel/net_guard.py`; unit tests (169.254.169.254 case)      |

## D — Denial of Service

| Đe dọa                           | Mitigation                                                                    | Cưỡng chế tại                                   |
| -------------------------------- | ----------------------------------------------------------------------------- | ----------------------------------------------- |
| Flood API                        | Rate limit per-caller 240 req/phút (fixed window, Retry-After); health exempt | `rate_limit.py` middleware + tests              |
| Provider LLM chết kéo sập worker | Timeout per-route + circuit breaker (5 lỗi liên tiếp → open 30s → half-open)  | `resilience.py` + `openai_compatible.py`; tests |
| Payload quá lớn                  | Tool timeout ≤600s, max_retries ≤10 enforced trong ToolDefinition schema      | `contracts.py` validators                       |

## E — Elevation of Privilege

| Đe dọa                        | Mitigation                                                                                                     | Cưỡng chế tại                   |
| ----------------------------- | -------------------------------------------------------------------------------------------------------------- | ------------------------------- |
| Gọi tool ngoài scope          | ToolExecutor bước 3: authorization theo `required_scopes` + approval policy trước khi execute; deny được audit | `executor.py`; permission tests |
| Ẩn nút UI làm "authorization" | UI không bao giờ là chốt: mọi route API check scope server-side; negative tests 403                            | routes + E2E                    |
| Plan thấp dùng tính năng cao  | Entitlement check tách khỏi authorization                                                                      | `entitlement.py`                |

## Ngoài phạm vi POC (ghi nhận, chưa mitigate)

- Rate limit phân tán (hiện per-process; chuyển Redis khi chạy nhiều instance).
- Điện tử hoá chữ ký approval (hiện chỉ audit + decide-once).
- Row-level crypto / BYOK cho artifact MinIO.
- DLP sâu trên nội dung transcript trước khi gửi LLM ngoài (hiện: cảnh báo cấu hình + provider tự chọn).
