"""An action nobody told the model about is an action nobody can ask for.

Adding a chat intent means touching three things: the ``ChatIntent`` Literal
(the model's output schema), the ``ACTIONS`` registry (what a reply about it
may claim), and the prompt bundle (how the model recognises it). The first two
are already bound to each other by ``test_action_receipt``. The third was not
bound to anything, so the failure mode was silent: the intent exists, the
handler works, the model never emits it because the prompt never mentions it.

This does not pull the prose into code — the wording is genuinely a prompt
concern and it lives in a versioned bundle for good reason. It only refuses
the state where the two disagree.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from dw_tender.application.conversation.actions import ACTIONS
from dw_tender.application.conversation.service import ConversationIntakeService

PROMPTS = Path(__file__).resolve().parents[4].parent / "configs" / "prompts" / "conversation"

# Recognised by the conversation flow rather than named to the model: the
# system decides when the person is at the confirmation step or mid-intake.
NOT_THE_MODELS_TO_PICK = {"draft_addendum"}


@pytest.fixture(scope="module")
def prompt_text() -> str:
    version = ConversationIntakeService.prompt_version
    path = PROMPTS / f"intake_chat@{version}.yaml"
    assert path.exists(), f"prompt bundle {path.name} is missing"
    bundle = yaml.safe_load(path.read_text(encoding="utf-8"))
    return f"{bundle['system']}\n{bundle['template']}"


def test_every_action_is_described_to_the_model(prompt_text: str) -> None:
    missing = sorted(
        name for name in ACTIONS if name not in NOT_THE_MODELS_TO_PICK and name not in prompt_text
    )
    assert missing == [], f"registered but never described in the prompt: {missing}"


def test_the_prompt_names_no_action_that_does_not_exist(prompt_text: str) -> None:
    """A leftover intent name in the prose teaches the model to emit garbage."""
    quoted = {
        word.strip(" \t:.,—-")
        for line in prompt_text.splitlines()
        if line.strip().startswith("- ")
        for word in [line.strip()[2:].split(":")[0]]
    }
    invented = sorted(w for w in quoted if "_" in w and " " not in w and w not in ACTIONS)
    assert invented == [], f"prompt names intents the registry does not have: {invented}"


def test_the_service_points_at_a_bundle_that_exists() -> None:
    version = ConversationIntakeService.prompt_version
    assert (PROMPTS / f"intake_chat@{version}.yaml").exists()
