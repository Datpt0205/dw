"""Integration: durable pause at approval, resume with a FRESH runner stack.

"Restart" is simulated by disposing every runtime object (engine, saver,
compiled graph, runner) and rebuilding from scratch — the only shared state is
PostgreSQL, which is exactly the durability claim being verified.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from runtime_harness import TENANT_B, RuntimeUrls, make_run_context
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dw_agent_runtime.adapters.checkpoint import SqlAlchemyCheckpointSaver
from dw_agent_runtime.adapters.langgraph_runner import LangGraphWorkflowRunner
from dw_agent_runtime.adapters.run_store import RunStatus, SqlWorkerRunStore
from dw_agent_runtime.adapters.runtime_tables import run_checkpoints
from dw_agent_runtime.context import access_context_from_run
from dw_agent_runtime.registry import GraphRegistry, WorkerRegistry
from dw_agent_runtime.testing.demo_graph import DEMO_WORKER_YAML, build_demo_graph
from dw_kernel.errors import ConflictError
from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_platform.adapters.persistence.uow import SqlPlatformUnitOfWorkFactory

pytestmark = pytest.mark.integration


class RunnerStack:
    """One 'process' worth of runtime objects."""

    def __init__(self, app_url: str, worker_config: Path) -> None:
        self.engine = create_async_engine(app_url, poolclass=NullPool)
        session_factory = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )
        graphs = GraphRegistry()
        graphs.register("demo_approval", "1.0.0", build_demo_graph)
        workers = WorkerRegistry(graph_registry=graphs)
        workers.load_file(worker_config)
        self.uow_factory = SqlPlatformUnitOfWorkFactory(session_factory)
        self.run_store = SqlWorkerRunStore(session_factory)
        self.runner = LangGraphWorkflowRunner(
            worker_registry=workers,
            graph_registry=graphs,
            checkpoint_saver=SqlAlchemyCheckpointSaver(session_factory),
            run_store=self.run_store,
            uow_factory=self.uow_factory,
            clock=SystemClock(),
            id_generator=Uuid4Generator(),
        )

    async def dispose(self) -> None:
        await self.engine.dispose()


@pytest.fixture
def worker_config(tmp_path: Path) -> Path:
    path = tmp_path / "demo_approval.yaml"
    path.write_text(DEMO_WORKER_YAML, encoding="utf-8")
    return path


async def test_pause_restart_resume_approved(urls: RuntimeUrls, worker_config: Path) -> None:
    context = make_run_context()

    # --- process 1: start, pause at approval ---
    stack1 = RunnerStack(urls.app, worker_config)
    run_id = await stack1.runner.start(
        run_context=context, input_payload={"subject": "Báo cáo quý 3"}
    )
    record = await stack1.run_store.get(context, run_id)
    assert record.status is RunStatus.WAITING_APPROVAL
    assert record.approval_request_id is not None

    # Approval request row really exists (via platform UoW under RLS).
    async with stack1.uow_factory(access_context_from_run(context)) as uow:
        approval = await uow.approvals.get(record.approval_request_id)
        assert approval is not None
        assert approval.approval_type == "demo.dispatch"
        assert approval.run_id == run_id
    await stack1.dispose()

    # --- process 2: brand-new stack resumes from the checkpoint ---
    stack2 = RunnerStack(urls.app, worker_config)
    await stack2.runner.resume(
        run_context=context,
        run_id=run_id,
        resume_payload={"approved": True, "comment": "Đồng ý"},
    )
    final = await stack2.run_store.get(context, run_id)
    assert final.status is RunStatus.COMPLETED
    assert final.result is not None
    assert final.result["dispatched"] is True
    assert final.result["approver_comment"] == "Đồng ý"

    # Audit trail covers the full lifecycle.
    async with stack2.uow_factory(access_context_from_run(context)) as uow:
        actions = [e.action for e in await uow.audit.list_recent(limit=50)]
    for expected in ("run.started", "run.waiting_approval", "run.resumed", "run.completed"):
        assert expected in actions
    await stack2.dispose()


async def test_rejected_resume_does_not_dispatch(urls: RuntimeUrls, worker_config: Path) -> None:
    context = make_run_context()
    stack = RunnerStack(urls.app, worker_config)
    run_id = await stack.runner.start(
        run_context=context, input_payload={"subject": "Nhiệm vụ nhạy cảm"}
    )
    await stack.runner.resume(
        run_context=context,
        run_id=run_id,
        resume_payload={"approved": False, "comment": "Từ chối"},
    )
    final = await stack.run_store.get(context, run_id)
    assert final.status is RunStatus.COMPLETED
    assert final.result is not None
    assert final.result["dispatched"] is False
    await stack.dispose()


async def test_resume_requires_waiting_state(urls: RuntimeUrls, worker_config: Path) -> None:
    context = make_run_context()
    stack = RunnerStack(urls.app, worker_config)
    run_id = await stack.runner.start(run_context=context, input_payload={"subject": "x"})
    await stack.runner.resume(run_context=context, run_id=run_id, resume_payload={"approved": True})
    with pytest.raises(ConflictError, match="not waiting"):
        await stack.runner.resume(
            run_context=context, run_id=run_id, resume_payload={"approved": True}
        )
    await stack.dispose()


async def test_checkpoints_are_tenant_isolated(urls: RuntimeUrls, worker_config: Path) -> None:
    context = make_run_context()
    stack = RunnerStack(urls.app, worker_config)
    await stack.runner.start(run_context=context, input_payload={"subject": "bí mật A"})

    engine = create_async_engine(urls.app, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            async with conn.begin():
                await conn.execute(
                    text("SELECT set_config('app.tenant_id', :t, true)"),
                    {"t": str(TENANT_B)},
                )
                rows = (await conn.execute(sa.select(run_checkpoints.c.run_id))).all()
                assert rows == [], "tenant B must not see tenant A checkpoints"
    finally:
        await engine.dispose()
    await stack.dispose()


async def test_worker_runs_visible_only_in_own_tenant(
    urls: RuntimeUrls, worker_config: Path
) -> None:
    context = make_run_context()
    stack = RunnerStack(urls.app, worker_config)
    run_id = await stack.runner.start(run_context=context, input_payload={"subject": "x"})

    foreign = make_run_context(tenant=TENANT_B, workspace=uuid.UUID(int=0xB01))
    from dw_kernel.errors import NotFoundError

    with pytest.raises(NotFoundError):
        await stack.run_store.get(foreign, run_id)
    await stack.dispose()
