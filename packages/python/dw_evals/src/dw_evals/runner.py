"""Evaluation runner: dataset file → graded cases → versioned report.

The runner is deliberately framework-free so `make eval-smoke` and CI can call
it directly. Reports are plain JSON under evals/reports.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from dw_evals.dataset import CaseCategory, EvalCase, EvalDataset
from dw_evals.graders import GRADERS, GraderContext, GradeResult


class CaseResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    category: CaseCategory
    grader: str
    passed: bool
    details: dict[str, Any] = {}


class EvalReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    dataset_id: str
    dataset_version: str
    worker_id: str
    total: int
    passed: int
    failed: int
    security_coverage_ok: bool
    results: tuple[CaseResult, ...]

    @property
    def ok(self) -> bool:
        return self.failed == 0 and self.security_coverage_ok


def load_dataset(path: Path) -> EvalDataset:
    return EvalDataset.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _load_ref(repo_root: Path, ref: str) -> dict[str, Any]:
    resolved = (repo_root / ref).resolve()
    if not resolved.is_relative_to(repo_root.resolve()):
        raise ValueError(f"case ref escapes the repository: {ref}")
    data = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"case ref must contain a JSON object: {ref}")
    return data


def _grade(ctx: GraderContext, repo_root: Path, case: EvalCase) -> GradeResult:
    grader = GRADERS.get(case.grader)
    if grader is None:
        return GradeResult.fail("unknown grader", grader=case.grader)
    try:
        input_data = _load_ref(repo_root, case.input_ref)
        expected = _load_ref(repo_root, case.expected_ref)
        return grader(ctx, input_data, expected)
    except Exception as exc:  # a crashing grader is a failing case, not a crash
        return GradeResult.fail("grader raised", error=f"{type(exc).__name__}: {exc}")


def run_dataset(dataset: EvalDataset, repo_root: Path) -> EvalReport:
    ctx = GraderContext(repo_root=repo_root)
    results = tuple(
        CaseResult(
            case_id=case.case_id,
            category=case.category,
            grader=case.grader,
            passed=(result := _grade(ctx, repo_root, case)).passed,
            details=result.details,
        )
        for case in dataset.cases
    )
    failed = sum(1 for result in results if not result.passed)
    return EvalReport(
        dataset_id=dataset.dataset_id,
        dataset_version=dataset.dataset_version,
        worker_id=dataset.worker_id,
        total=len(results),
        passed=len(results) - failed,
        failed=failed,
        security_coverage_ok=dataset.has_full_security_coverage(),
        results=results,
    )


def write_report(report: EvalReport, reports_dir: Path) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{report.dataset_id}@{report.dataset_version}.json"
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return path
