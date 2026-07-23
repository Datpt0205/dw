# ADR-004: LangGraph cho agent workflow; Temporal deferred sau port

- **Status**: Accepted
- **Date**: 2026-07-23

## Context

Cần workflow engine hỗ trợ typed state graph, checkpoint, interrupt/resume cho
human-in-the-loop. Temporal mạnh về durable execution nhưng nặng cho POC.

## Decision

- LangGraph là engine agentic workflow của POC: typed versioned state, checkpoint
  persistence vào PostgreSQL, interrupt ↔ approval mapping.
- Toàn bộ LangGraph nằm trong adapter của `dw_agent_runtime`
  (`LangGraphWorkflowRunner` implement `WorkflowRunnerPort`). Workflow node gọi
  application service/port; cấm import LangGraph từ domain/application/presentation
  (enforce bằng import-linter).
- Temporal được thêm sau (nếu cần durable long-running thật sự) bằng một
  `TemporalWorkflowRunner` mới cùng port — không đổi domain.

## Consequences

- Đổi/nâng version LangGraph chỉ chạm một adapter; test checkpoint/resume là guard.
- `WorkflowRunnerPort.start/resume` là contract ổn định cho API và UI.
