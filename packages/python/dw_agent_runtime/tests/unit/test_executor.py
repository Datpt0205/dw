import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from pydantic import BaseModel

from dw_agent_runtime.contracts import RunContext, ToolDefinition
from dw_agent_runtime.executor import ToolExecutor
from dw_agent_runtime.tools import RegisteredTool, ToolRegistry
from dw_kernel.errors import (
    ApprovalRequiredError,
    DomainError,
    IdempotencyConflictError,
    InfrastructureError,
    PermissionDeniedError,
)
from dw_kernel.ports import FixedClock, SequentialIdGenerator
from dw_platform.application.access_context import AccessContext
from dw_platform.application.ports import PlatformUnitOfWork
from dw_platform.domain.audit import AuditEvent

pytestmark = pytest.mark.unit

NOW = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)


class EchoInput(BaseModel):
    message: str


class EchoOutput(BaseModel):
    echoed: str


@dataclass
class FakeExecutionStore:
    succeeded: dict[tuple[str, str], Any] = field(default_factory=dict)
    records: list[dict[str, Any]] = field(default_factory=list)

    async def find_succeeded(self, run_context, tool_name, idempotency_key):
        return self.succeeded.get((tool_name, idempotency_key))

    async def record(self, run_context, **kwargs):
        self.records.append(kwargs)
        if kwargs.get("status") == "succeeded" and kwargs.get("idempotency_key"):
            entry = type(
                "Stored",
                (),
                {
                    "input_hash": kwargs["input_hash"],
                    "output": kwargs["output"],
                },
            )()
            self.succeeded[(kwargs["tool_name"], kwargs["idempotency_key"])] = entry


@dataclass
class FakeAuditRepo:
    events: list[AuditEvent] = field(default_factory=list)

    async def append(self, event: AuditEvent) -> None:
        self.events.append(event)

    async def list_recent(self, limit: int = 50) -> list[AuditEvent]:
        return self.events[-limit:]


@dataclass
class FakeUoW:
    audit: FakeAuditRepo
    approvals: Any = None
    outbox: Any = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


@dataclass
class FakeUoWFactory:
    audit_repo: FakeAuditRepo = field(default_factory=FakeAuditRepo)

    def __call__(self, context: AccessContext) -> "PlatformUnitOfWork":
        return cast("PlatformUnitOfWork", FakeUoW(audit=self.audit_repo))


def make_definition(**overrides: object) -> ToolDefinition:
    defaults: dict[str, object] = {
        "name": "test.echo",
        "version": "1.0.0",
        "description": "Echo",
        "input_schema_ref": "contracts/tools/test.echo/input.json",
        "output_schema_ref": "contracts/tools/test.echo/output.json",
        "required_scopes": frozenset({"work_ops.write"}),
        "side_effect_level": "external",
        "approval_policy": "never",
        "timeout_seconds": 2,
        "max_retries": 2,
        "idempotent": True,
        "data_classification": frozenset({"internal"}),
    }
    defaults.update(overrides)
    return ToolDefinition(**defaults)


def make_run_context(scopes: frozenset[str] = frozenset({"work_ops.write"})) -> RunContext:
    return RunContext(
        run_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        worker_id="demo_approval",
        worker_version="1.0.0",
        channel="web",
        plan_id="professional",
        roles=frozenset({"member"}),
        scopes=scopes,
        trace_id="trace-1",
    )


def make_executor(handler, definition: ToolDefinition | None = None):
    registry = ToolRegistry()
    registry.register(
        RegisteredTool(
            definition=definition or make_definition(),
            input_model=EchoInput,
            output_model=EchoOutput,
            handler=handler,
        )
    )
    store = FakeExecutionStore()
    uow_factory = FakeUoWFactory()

    async def no_sleep(_: float) -> None: ...

    executor = ToolExecutor(
        registry=registry,
        execution_store=store,
        uow_factory=uow_factory,
        clock=FixedClock(NOW),
        id_generator=SequentialIdGenerator(),
        sleep=no_sleep,
    )
    return executor, store, uow_factory.audit_repo


async def echo_handler(payload: EchoInput, run_context: RunContext) -> EchoOutput:
    return EchoOutput(echoed=payload.message)


async def test_happy_path_returns_typed_output_and_audits() -> None:
    executor, store, audit = make_executor(echo_handler)
    output = await executor.execute(
        name="test.echo",
        version="1.0.0",
        raw_input={"message": "xin chào"},
        run_context=make_run_context(),
        idempotency_key="k1",
    )
    assert isinstance(output, EchoOutput) and output.echoed == "xin chào"
    assert store.records[-1]["status"] == "succeeded"
    assert [e.action for e in audit.events] == ["tool.executed"]
    assert audit.events[0].policy_decision == "allow"


async def test_missing_scope_denied_and_audited() -> None:
    executor, _, audit = make_executor(echo_handler)
    with pytest.raises(PermissionDeniedError, match="scopes"):
        await executor.execute(
            name="test.echo",
            version="1.0.0",
            raw_input={"message": "x"},
            run_context=make_run_context(scopes=frozenset({"tender.read"})),
            idempotency_key="k1",
        )
    assert [e.action for e in audit.events] == ["tool.denied"]
    assert audit.events[0].policy_decision == "deny_missing_scope"


async def test_critical_tool_requires_approval() -> None:
    definition = make_definition(side_effect_level="critical")
    executor, _, _audit = make_executor(echo_handler, definition)
    with pytest.raises(ApprovalRequiredError):
        await executor.execute(
            name="test.echo",
            version="1.0.0",
            raw_input={"message": "x"},
            run_context=make_run_context(),
            idempotency_key="k1",
        )
    # With explicit approval it executes.
    output = await executor.execute(
        name="test.echo",
        version="1.0.0",
        raw_input={"message": "x"},
        run_context=make_run_context(),
        idempotency_key="k1",
        approved=True,
    )
    assert isinstance(output, EchoOutput)


async def test_side_effect_requires_idempotency_key() -> None:
    executor, _, _ = make_executor(echo_handler)
    with pytest.raises(DomainError, match="idempotency"):
        await executor.execute(
            name="test.echo",
            version="1.0.0",
            raw_input={"message": "x"},
            run_context=make_run_context(),
        )


async def test_replay_returns_cached_output_without_reexecution() -> None:
    calls = 0

    async def counting_handler(payload: EchoInput, run_context: RunContext) -> EchoOutput:
        nonlocal calls
        calls += 1
        return EchoOutput(echoed=payload.message)

    executor, _, audit = make_executor(counting_handler)
    context = make_run_context()
    first = await executor.execute(
        name="test.echo",
        version="1.0.0",
        raw_input={"message": "a"},
        run_context=context,
        idempotency_key="same-key",
    )
    second = await executor.execute(
        name="test.echo",
        version="1.0.0",
        raw_input={"message": "a"},
        run_context=context,
        idempotency_key="same-key",
    )
    assert calls == 1, "second call must be a replay, not a re-execution"
    assert first == second
    assert audit.events[-1].action == "tool.replayed"


async def test_same_key_different_payload_conflicts() -> None:
    executor, _, _ = make_executor(echo_handler)
    context = make_run_context()
    await executor.execute(
        name="test.echo",
        version="1.0.0",
        raw_input={"message": "a"},
        run_context=context,
        idempotency_key="key",
    )
    with pytest.raises(IdempotencyConflictError):
        await executor.execute(
            name="test.echo",
            version="1.0.0",
            raw_input={"message": "DIFFERENT"},
            run_context=context,
            idempotency_key="key",
        )


async def test_invalid_input_rejected_before_execution() -> None:
    executor, store, _ = make_executor(echo_handler)
    with pytest.raises(DomainError, match="input"):
        await executor.execute(
            name="test.echo",
            version="1.0.0",
            raw_input={"wrong": 1},
            run_context=make_run_context(),
            idempotency_key="k",
        )
    assert store.records == []


async def test_transient_failure_retries_then_succeeds() -> None:
    attempts = 0

    async def flaky_handler(payload: EchoInput, run_context: RunContext) -> EchoOutput:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise InfrastructureError("upstream blip")
        return EchoOutput(echoed=payload.message)

    executor, store, _ = make_executor(flaky_handler)
    output = await executor.execute(
        name="test.echo",
        version="1.0.0",
        raw_input={"message": "ok"},
        run_context=make_run_context(),
        idempotency_key="k",
    )
    assert isinstance(output, EchoOutput)
    assert attempts == 3
    assert store.records[-1]["attempts"] == 3


async def test_timeout_is_bounded_and_recorded_as_failure() -> None:
    async def hanging_handler(payload: EchoInput, run_context: RunContext) -> EchoOutput:
        await asyncio.sleep(60)
        return EchoOutput(echoed="never")

    definition = make_definition(timeout_seconds=1, max_retries=0)
    executor, store, audit = make_executor(hanging_handler, definition)
    with pytest.raises(InfrastructureError, match="failed"):
        await executor.execute(
            name="test.echo",
            version="1.0.0",
            raw_input={"message": "x"},
            run_context=make_run_context(),
            idempotency_key="k",
        )
    assert store.records[-1]["status"] == "failed"
    assert audit.events[-1].action == "tool.failed"


async def test_output_schema_violation_is_domain_error() -> None:
    async def bad_output_handler(payload: EchoInput, run_context: RunContext):
        return {"unexpected": True}

    executor, _, _ = make_executor(bad_output_handler)
    with pytest.raises(DomainError, match="output"):
        await executor.execute(
            name="test.echo",
            version="1.0.0",
            raw_input={"message": "x"},
            run_context=make_run_context(),
            idempotency_key="k",
        )
