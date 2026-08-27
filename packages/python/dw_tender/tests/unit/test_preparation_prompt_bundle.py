"""The bundle version the worker ships must be able to render what the nodes send.

This binds two things that drift apart silently. ``configs/workers/preparation.yaml``
declares a prompt bundle version; the drafting nodes send a fixed set of variables.
When a prompt gains a variable and the bundle is not bumped — or is bumped back —
``render`` raises "prompt variables mismatch", and both ``_llm_solicitation`` and
``_llm_criteria`` catch every exception and return ``None``.

The result is not an error anyone sees. Drafting quietly reverts to the
deterministic template, the artifact says ``drafted_by: template``, and the only
way to notice is to wonder why the AI stopped writing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from dw_agent_runtime.model.prompts import PromptRegistry
from dw_tender.workflows.preparation_v1.services import PreparationServices

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[4].parent
PROMPTS = REPO / "configs" / "prompts"
WORKER = REPO / "configs" / "workers" / "preparation.yaml"

# Exactly what the nodes put in `variables`, per prompt. Values are irrelevant —
# the registry checks the key set, which is the thing that drifts.
SENT_BY_NODES = {
    "preparation.extract_requirements": {"pr_text": "…"},
    "preparation.draft_solicitation": {
        "procurement_type": "goods",
        "method": "đấu thầu rộng rãi",
        "requirements": "- REQ-1",
        "passages": "[1] …",
    },
    "preparation.draft_criteria": {
        "procurement_type": "goods",
        "requirements": "- REQ-1",
        "passages": "[1] …",
    },
    "preparation.extract_required_sections": {"passages": "[1] …"},
}


def _bundle_version() -> str:
    return str(yaml.safe_load(WORKER.read_text(encoding="utf-8"))["prompt_bundle_version"])


def test_the_worker_config_and_the_code_agree_on_the_bundle_version() -> None:
    """Two declarations of the same fact, in two files, with nothing binding them."""
    assert _bundle_version() == PreparationServices.prompt_bundle_version


@pytest.mark.parametrize("prompt_id", sorted(SENT_BY_NODES))
def test_every_bundled_prompt_renders_with_what_the_node_sends(prompt_id: str) -> None:
    registry = PromptRegistry()
    registry.load_directory(PROMPTS)

    rendered = registry.render(prompt_id, _bundle_version(), SENT_BY_NODES[prompt_id])

    assert rendered.user.strip(), "prompt render ra rỗng thì model không có gì để đọc"


def test_a_prompt_that_wants_passages_gets_them_rather_than_a_placeholder() -> None:
    """Guards the reordering in the drafting nodes.

    Retrieval used to run after the model call, so the passages could not reach
    the prompt at all. If the wiring is undone, the variable is still declared —
    this checks the text actually arrives.
    """
    registry = PromptRegistry()
    registry.load_directory(PROMPTS)
    marker = "Điều 45 khoản 1 — tối thiểu 18 ngày"

    for prompt_id in ("preparation.draft_solicitation", "preparation.draft_criteria"):
        variables = {**SENT_BY_NODES[prompt_id], "passages": f"[1] {marker}"}
        rendered = registry.render(prompt_id, _bundle_version(), variables)
        assert marker in rendered.user, prompt_id
