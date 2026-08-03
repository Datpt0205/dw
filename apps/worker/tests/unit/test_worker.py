import asyncio
from pathlib import Path

import pytest

from dw_kernel.errors import InfrastructureError
from dw_worker.consumers import ConsumerRegistry
from dw_worker.consumers.slack_approvals import _slack_failure
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


def test_slack_settings_require_all_demo_member_mappings() -> None:
    settings = WorkerSettings(
        database_url="postgresql+asyncpg://dw:dw@localhost/dw",
        slack_approvals_enabled=True,
        slack_bot_token="xoxb-test",
        slack_user_an_id="UAN",
        slack_user_binh_id="UBINH",
    )
    with pytest.raises(RuntimeError, match=r"dev\|chi.le"):
        settings.validate_slack()


def test_slack_settings_build_subject_to_member_map() -> None:
    settings = WorkerSettings(
        slack_user_an_id="UAN",
        slack_user_binh_id="UBINH",
        slack_user_chi_id="UCHI",
        slack_user_map_json='{"oidc|other":"UOTHER"}',
    )
    assert settings.slack_user_map() == {
        "dev|an.nguyen": "UAN",
        "dev|binh.tran": "UBINH",
        "dev|chi.le": "UCHI",
        "oidc|other": "UOTHER",
    }


def test_slack_user_not_found_is_friendly_and_not_retried() -> None:
    error = InfrastructureError(
        "Slack rejected the request",
        details={"slack_error": "user_not_found"},
    )
    message, permanent, code = _slack_failure(error)

    assert permanent is True
    assert code == "user_not_found"
    assert "không tìm thấy thành viên" in message


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
