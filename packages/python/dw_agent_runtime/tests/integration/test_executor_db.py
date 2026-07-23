"""Integration: tool executor idempotency + audit against real Postgres."""

from __future__ import annotations

import pytest
from pydantic import BaseModel
from runtime_harness import RuntimeUrls, make_run_context
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dw_agent_runtime.adapters.tool_execution_store import SqlToolExecutionStore
from dw_agent_runtime.context import access_context_from_run
from dw_agent_runtime.contracts import RunContext, ToolDefinition
from dw_agent_runtime.executor import ToolExecutor
from dw_agent_runtime.tools import RegisteredTool, ToolRegistry
from dw_kernel.errors import IdempotencyConflictError, PermissionDeniedError
from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_platform.adapters.persistence.uow import SqlPlatformUnitOfWorkFactory

pytestmark = pytest.mark.integration


class DispatchInput(BaseModel):
    action: str


class DispatchOutput(BaseModel):
    external_ref: str


def build_executor(app_url: str) -> tuple[ToolExecutor, SqlPlatformUnitOfWorkFactory, list[int]]:
    engine = create_async_engine(app_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    call_counter = [0]

    async def dispatch_handler(payload: BaseModel, run_context: RunContext) -> DispatchOutput:
        call_counter[0] += 1
        assert isinstance(payload, DispatchInput)
        return DispatchOutput(external_ref=f"EXT-{payload.action}-{call_counter[0]}")

    registry = ToolRegistry()
    registry.register(
        RegisteredTool(
            definition=ToolDefinition(
                name="task.dispatch",
                version="1.0.0",
                description="Dispatch a task externally",
                input_schema_ref="contracts/tools/task.dispatch/input.json",
                output_schema_ref="contracts/tools/task.dispatch/output.json",
                required_scopes=frozenset({"work_ops.write"}),
                side_effect_level="external",
                approval_policy="never",
                timeout_seconds=10,
                max_retries=1,
                idempotent=True,
                data_classification=frozenset({"internal"}),
            ),
            input_model=DispatchInput,
            output_model=DispatchOutput,
            handler=dispatch_handler,
        )
    )
    uow_factory = SqlPlatformUnitOfWorkFactory(session_factory)
    executor = ToolExecutor(
        registry=registry,
        execution_store=SqlToolExecutionStore(session_factory),
        uow_factory=uow_factory,
        clock=SystemClock(),
        id_generator=Uuid4Generator(),
    )
    return executor, uow_factory, call_counter


async def test_idempotent_dispatch_survives_retry(urls: RuntimeUrls) -> None:
    executor, _, calls = build_executor(urls.app)
    context = make_run_context()
    key = f"{context.tenant_id}:action-1:mock:1.0.0"

    first = await executor.execute(
        name="task.dispatch",
        version="1.0.0",
        raw_input={"action": "a1"},
        run_context=context,
        idempotency_key=key,
    )
    second = await executor.execute(
        name="task.dispatch",
        version="1.0.0",
        raw_input={"action": "a1"},
        run_context=context,
        idempotency_key=key,
    )
    assert calls[0] == 1, "retry with the same key must not create a second side effect"
    assert first == second

    with pytest.raises(IdempotencyConflictError):
        await executor.execute(
            name="task.dispatch",
            version="1.0.0",
            raw_input={"action": "DIFFERENT"},
            run_context=context,
            idempotency_key=key,
        )


async def test_denied_tool_call_is_audited(urls: RuntimeUrls) -> None:
    executor, uow_factory, _ = build_executor(urls.app)
    context = make_run_context(scopes=frozenset({"tender.read"}))  # missing work_ops.write

    with pytest.raises(PermissionDeniedError):
        await executor.execute(
            name="task.dispatch",
            version="1.0.0",
            raw_input={"action": "a"},
            run_context=context,
            idempotency_key="k",
        )

    async with uow_factory(access_context_from_run(context)) as uow:
        events = await uow.audit.list_recent(limit=10)
    denied = [e for e in events if e.action == "tool.denied"]
    assert denied, "denied tool call must leave an audit event"
    assert denied[0].policy_decision == "deny_missing_scope"
    assert denied[0].resource_id == "task.dispatch@1.0.0"
