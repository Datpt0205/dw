import pytest
from pydantic import ValidationError

from dw_evals.dataset import CaseCategory, EvalCase, EvalDataset

pytestmark = pytest.mark.unit


def make_case(case_id: str, category: CaseCategory) -> EvalCase:
    return EvalCase(
        case_id=case_id,
        category=category,
        description="d",
        input_ref=f"evals/datasets/work_ops/{case_id}.json",
        expected_ref=f"evals/expected/work_ops/{case_id}.json",
        grader="deterministic.action_match",
    )


def make_dataset(cases: list[EvalCase]) -> EvalDataset:
    return EvalDataset(
        dataset_id="work_ops_golden",
        dataset_version="1.0.0",
        worker_id="work_ops",
        cases=tuple(cases),
    )


def test_dataset_version_must_be_semver() -> None:
    with pytest.raises(ValidationError):
        EvalDataset(dataset_id="x", dataset_version="v1", worker_id="work_ops", cases=())


def test_duplicate_case_ids_rejected() -> None:
    case = make_case("c1", CaseCategory.NORMAL)
    with pytest.raises(ValidationError):
        make_dataset([case, case])


def test_security_coverage_detection() -> None:
    partial = make_dataset(
        [
            make_case("c1", CaseCategory.NORMAL),
            make_case("c2", CaseCategory.PROMPT_INJECTION),
        ]
    )
    assert not partial.has_full_security_coverage()

    full = make_dataset(
        [
            make_case("c1", CaseCategory.PROMPT_INJECTION),
            make_case("c2", CaseCategory.CROSS_TENANT_ATTACK),
            make_case("c3", CaseCategory.MISSING_EVIDENCE),
        ]
    )
    assert full.has_full_security_coverage()
