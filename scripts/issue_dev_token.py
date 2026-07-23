"""Issue a local dev JWT for a seeded demo user (ADR-013; local/test only).

Usage:
  uv run python scripts/issue_dev_token.py dev|an.nguyen
  uv run python scripts/issue_dev_token.py dev|an.nguyen --hours 24
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import timedelta

from dw_platform.adapters.identity.dev_token import DevTokenVerifier


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("subject", help="token subject, e.g. dev|an.nguyen")
    parser.add_argument("--email", default=None)
    parser.add_argument("--hours", type=float, default=8.0)
    parser.add_argument(
        "--secret",
        default=os.environ.get("DW_API_DEV_SECRET") or os.environ.get("DW_AUTH_DEV_SECRET"),
        help="dev secret (defaults to DW_API_DEV_SECRET)",
    )
    args = parser.parse_args()
    if not args.secret:
        print("ERROR: provide --secret or set DW_API_DEV_SECRET", file=sys.stderr)
        return 2

    verifier = DevTokenVerifier(args.secret)
    token = verifier.issue(args.subject, email=args.email, ttl=timedelta(hours=args.hours))
    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
