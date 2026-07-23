"""Worker main loop: runs registered consumers and keeps the heartbeat fresh.

Phase 0 ships the durable loop + heartbeat + graceful shutdown; outbox and
workflow consumers register here in later phases.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

from dw_worker.consumers import ConsumerRegistry
from dw_worker.health import beat
from dw_worker.settings import WorkerSettings

logger = logging.getLogger("dw_worker")


async def run_worker(
    settings: WorkerSettings,
    registry: ConsumerRegistry,
    shutdown_event: asyncio.Event,
) -> None:
    logger.info("worker starting, consumers=%s", sorted(registry.all()))

    async def heartbeat_loop() -> None:
        while not shutdown_event.is_set():
            beat(settings.heartbeat_file)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    shutdown_event.wait(), timeout=settings.heartbeat_interval_seconds
                )

    async def consumer_loop(name: str) -> None:
        consumer = registry.all()[name]
        while not shutdown_event.is_set():
            try:
                await consumer()
            except Exception:
                logger.exception("consumer %s failed; backing off", name)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    shutdown_event.wait(), timeout=settings.poll_interval_seconds
                )

    tasks = [asyncio.create_task(heartbeat_loop(), name="heartbeat")]
    tasks.extend(
        asyncio.create_task(consumer_loop(name), name=f"consumer:{name}") for name in registry.all()
    )
    await shutdown_event.wait()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    logger.info("worker stopped cleanly")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    settings = WorkerSettings()
    registry = ConsumerRegistry()
    shutdown_event = asyncio.Event()

    async def runner() -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError):  # Windows lacks add_signal_handler
                loop.add_signal_handler(sig, shutdown_event.set)
        await run_worker(settings, registry, shutdown_event)

    asyncio.run(runner())


if __name__ == "__main__":
    main()
