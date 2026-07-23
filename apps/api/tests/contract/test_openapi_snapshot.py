"""Contract test: the committed OpenAPI snapshot matches the live app schema."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SNAPSHOT = REPO_ROOT / "contracts" / "openapi" / "openapi.json"

pytestmark = pytest.mark.contract

sys.path.insert(0, str(REPO_ROOT / "scripts"))


def test_openapi_snapshot_is_current() -> None:
    from generate_contracts import build_openapi  # type: ignore[import-not-found]

    assert SNAPSHOT.exists(), "run `make generate-contracts` to create the snapshot"
    committed = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    live = json.loads(json.dumps(build_openapi(), sort_keys=True))
    assert committed == live, "OpenAPI drifted — run `make generate-contracts` and commit"


def test_key_endpoints_present() -> None:
    from generate_contracts import build_openapi

    paths = build_openapi()["paths"]
    for expected in (
        "/api/v1/health",
        "/api/v1/me",
        "/api/v1/approvals",
        "/api/v1/approvals/{approval_id}/decisions",
        "/api/v1/runs/{run_id}",
        "/api/v1/work-ops/meetings",
        "/api/v1/work-ops/meetings/{meeting_id}/generate-actions",
        "/api/v1/audit/events",
    ):
        assert expected in paths, f"missing endpoint {expected}"
