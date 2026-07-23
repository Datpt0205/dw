import asyncio
from pathlib import Path

import pytest

from dw_worker.consumers import ConsumerRegistry
from dw_worker.health import beat, is_alive
from dw_worker.main import run_worker
from dw_worker.settings import WorkerSettings

pytestmark = pytest.mark.unit


def test_heartbeat_roundtrip(tmp_path: Path) -> None:
    hb = tmp_path / "heartbeat"
    beat(hb)
    assert is_alive(hb, max_age_seconds=10)
    assert not is_alive(tmp_path / "missing", max_age_seconds=10)


def test_registry_rejects_duplicates_and_blank_names() -> None:
    registry = ConsumerRegistry()

    async def consumer() -> None: ...

    registry.register("outbox", consumer)
    with pytest.raises(ValueError, match="already registered"):
        registry.register("outbox", consumer)
    with pytest.raises(ValueError, match="blank"):
        registry.register("  ", consumer)


async def test_worker_runs_consumers_and_shuts_down(tmp_path: Path) -> None:
    settings = WorkerSettings(
        heartbeat_file=tmp_path / "hb",
        heartbeat_interval_seconds=0.05,
        poll_interval_seconds=0.05,
    )
    registry = ConsumerRegistry()
    calls = 0

    async def counting_consumer() -> None:
        nonlocal calls
        calls += 1

    registry.register("counter", counting_consumer)
    shutdown = asyncio.Event()

    worker_task = asyncio.create_task(run_worker(settings, registry, shutdown))
    await asyncio.sleep(0.3)
    shutdown.set()
    await asyncio.wait_for(worker_task, timeout=2)

    assert calls >= 2, "consumer should run repeatedly"
    assert is_alive(settings.heartbeat_file, max_age_seconds=5)


async def test_failing_consumer_does_not_kill_worker(tmp_path: Path) -> None:
    settings = WorkerSettings(
        heartbeat_file=tmp_path / "hb",
        heartbeat_interval_seconds=0.05,
        poll_interval_seconds=0.05,
    )
    registry = ConsumerRegistry()

    async def broken_consumer() -> None:
        raise RuntimeError("boom")

    registry.register("broken", broken_consumer)
    shutdown = asyncio.Event()
    worker_task = asyncio.create_task(run_worker(settings, registry, shutdown))
    await asyncio.sleep(0.3)
    assert not worker_task.done(), "worker must survive consumer failures"
    shutdown.set()
    await asyncio.wait_for(worker_task, timeout=2)
