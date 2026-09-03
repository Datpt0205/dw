# Digital Worker Source Base - Start Here

## Bộ tài liệu này dùng để làm gì

Đây là specification pack để Claude Code tạo source base ban đầu cho nền tảng Digital Worker gồm hai bounded context:

- Procurement Tender Digital Worker.
- Executive Work Coordination Digital Worker.

## Thứ tự đọc bắt buộc

1. `CLAUDE.md` - quy tắc thực thi và các điều không được vi phạm.
2. `docs/architecture/Digital_Worker_Source_Base_Blueprint_v2.md` - đặc tả kiến trúc đầy đủ.
3. Các ADR mà Claude Code tạo trong quá trình bootstrap.

## Prompt khởi động đề xuất

```text
Read CLAUDE.md and docs/architecture/Digital_Worker_Source_Base_Blueprint_v2.md completely.
Treat them as binding implementation specifications.

First inspect the repository and report:
1. Current repository state.
2. Assumptions and unresolved decisions.
3. A phased implementation plan mapped to sections 28 and 29 of the blueprint.
4. The exact files to create in Phase 0.

Then implement Phase 0 only:
- bootstrap the monorepo/workspaces;
- create architecture boundary tests;
- create Docker Compose and example environment configuration;
- create executable Make/Task commands;
- create README, ADR-001 through ADR-004 and progress tracking;
- make `make bootstrap`, `make lint`, and `make test-unit` pass.

Do not create empty placeholder packages. Every deferred external dependency must have a typed port and a working mock adapter. Do not proceed to Phase 1 until Phase 0 acceptance criteria pass and you show the test results.
```

## Cách dùng

Copy toàn bộ nội dung pack vào root repository. Mở Claude Code tại root, gửi prompt trên, review plan rồi cho chạy từng phase. Không yêu cầu Claude Code dựng toàn bộ hệ thống trong một lần.

Sau khi Phase 0 xong, vòng lặp làm việc hằng ngày (setup, checklist trước khi prompt, rule cứng, quality gate) nằm ở [`docs/development/DEV_WORKFLOW.md`](docs/development/DEV_WORKFLOW.md).
