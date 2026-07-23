"""Run evaluation datasets and write versioned reports.

Usage:
    uv run python scripts/run_evals.py --smoke              # all datasets
    uv run python scripts/run_evals.py --dataset evals/datasets/tender@1.0.0.json

Exit code is non-zero when any case fails or a dataset lacks full security
coverage (prompt injection, cross-tenant attack, missing evidence).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASETS_DIR = REPO_ROOT / "evals" / "datasets"
REPORTS_DIR = REPO_ROOT / "evals" / "reports"


def main() -> int:
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true", help="run every dataset in evals/datasets")
    parser.add_argument("--dataset", type=Path, help="run a single dataset file")
    args = parser.parse_args()

    from dw_evals.runner import load_dataset, run_dataset, write_report

    if args.dataset:
        paths = [args.dataset]
    else:
        paths = sorted(DATASETS_DIR.glob("*.json"))
        if not args.smoke:
            parser.error("pass --smoke or --dataset <file>")
    if not paths:
        print("ERROR: no datasets found under evals/datasets", file=sys.stderr)
        return 1

    exit_code = 0
    for path in paths:
        dataset = load_dataset(path)
        report = run_dataset(dataset, REPO_ROOT)
        report_path = write_report(report, REPORTS_DIR)
        status = "PASS" if report.ok else "FAIL"
        print(
            f"[{status}] {report.dataset_id}@{report.dataset_version} "
            f"({report.worker_id}): {report.passed}/{report.total} cases, "
            f"security coverage {'ok' if report.security_coverage_ok else 'MISSING'} "
            f"→ {report_path.relative_to(REPO_ROOT)}"
        )
        for result in report.results:
            if not result.passed:
                print(f"    ✗ {result.case_id} [{result.category}] {result.details}")
        if not report.ok:
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
