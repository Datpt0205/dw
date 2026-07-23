"""Export the OpenAPI snapshot (contracts/openapi/openapi.json).

The API app is built with placeholder connection strings — no live services are
contacted; engines/clients are lazy. The snapshot is the contract-test baseline
and the source for the generated TypeScript types.

Usage:
  uv run python scripts/generate_contracts.py          # write snapshot
  uv run python scripts/generate_contracts.py --check  # fail if drifted
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = REPO_ROOT / "contracts" / "openapi" / "openapi.json"


def build_openapi() -> dict[str, object]:
    from dw_api.bootstrap import build_container
    from dw_api.main import create_app
    from dw_api.settings import ApiSettings

    settings = ApiSettings(
        profile="test",
        database_url="postgresql+asyncpg://contract:contract@localhost:5432/contract",
        auth_mode="dev",
        dev_secret="contract-snapshot-secret-0123456789",
        s3_endpoint_url="http://localhost:9000",
        s3_access_key="contract",
        s3_secret_key="contract",
        model_provider="mock",
    )
    app = create_app(build_container(settings))
    schema = app.openapi()
    return schema


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify snapshot is current")
    args = parser.parse_args()

    schema = build_openapi()
    rendered = json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    if args.check:
        if not SNAPSHOT.exists() or SNAPSHOT.read_text(encoding="utf-8") != rendered:
            print(
                "OpenAPI snapshot is stale — run `make generate-contracts`",
                file=sys.stderr,
            )
            return 1
        print("OpenAPI snapshot is current.")
        return 0

    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(rendered, encoding="utf-8")
    print(f"Wrote {SNAPSHOT.relative_to(REPO_ROOT)} ({len(rendered)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
