"""File-based heartbeat used by the container healthcheck.

The worker touches the heartbeat file on every loop; the healthcheck fails when
the file is stale, which catches hangs as well as crashes.
"""

from __future__ import annotations

import time
from pathlib import Path


def beat(heartbeat_file: Path) -> None:
    heartbeat_file.parent.mkdir(parents=True, exist_ok=True)
    heartbeat_file.write_text(str(time.time()), encoding="utf-8")


def is_alive(heartbeat_file: Path, max_age_seconds: float) -> bool:
    try:
        last_beat = float(heartbeat_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    return (time.time() - last_beat) <= max_age_seconds


def healthcheck_main() -> int:
    """Entry point for `python -m dw_worker.health` inside the container."""
    from dw_worker.settings import WorkerSettings

    settings = WorkerSettings()
    max_age = settings.heartbeat_interval_seconds * 4
    return 0 if is_alive(settings.heartbeat_file, max_age) else 1


if __name__ == "__main__":
    raise SystemExit(healthcheck_main())
