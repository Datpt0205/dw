"""Show the model the shape of the answer, never the schema that describes it.

Under ``json_schema`` the schema never reaches the model as text — the provider
compiles it into a decoding constraint. Under ``json_object`` it is pasted into
the prompt, and "return a JSON object matching this schema" next to a JSON
object gets the schema echoed straight back.

That is what broke the approval classifier on a provider without constrained
decoding. The model returned the schema document itself: valid JSON, parsed
cleanly, and validated cleanly too, because every real field was absent and
Pydantic supplied its defaults. An explicit "duyệt cp2 hồ sơ do Lê Thu Hà đề
nghị" arrived as ``decision="none"`` — a refusal the defaults invented, with no
exception and nothing in a log. Measured 2/5 correct before, 15/15 after.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from dw_agent_runtime.adapters.openai_compatible import _drop_nulls, _schema_as_instruction


class _Decision(BaseModel):
    decision: Literal["approve", "reject", "none"] = "none"
    stage: Literal["intake", "checkpoint", "any"] = "any"
    target: str = Field(default="", description="Tên hồ sơ người dùng nhắc tới")


class _Addendum(BaseModel):
    change_summary: str = ""
    extend_bids_by_days: int | None = None


class _Turn(BaseModel):
    intent: Literal["approve", "other"] = "other"
    certain: bool = False
    addendum: _Addendum | None = None
    supplier_names: list[str] = Field(default_factory=list)


def test_the_skeleton_is_shaped_like_the_answer() -> None:
    assert _schema_as_instruction(_Decision.model_json_schema()) == {
        "decision": "<approve|reject|none>",
        "stage": "<intake|checkpoint|any>",
        "target": "<Tên hồ sơ người dùng nhắc tới>",
    }


def test_nothing_of_the_schema_vocabulary_survives() -> None:
    """`properties`, `title`, `type`, `default` are what the model echoed."""
    rendered = str(_schema_as_instruction(_Decision.model_json_schema()))
    for leaked in ("properties", "title", "type", "default", "enum"):
        assert leaked not in rendered


def test_choices_are_still_visible_as_choices() -> None:
    """Stripping the schema must not strip what the field may contain."""
    skeleton = _schema_as_instruction(_Decision.model_json_schema())
    assert isinstance(skeleton, dict)
    assert skeleton["decision"] == "<approve|reject|none>"


def test_booleans_numbers_and_lists_get_their_own_slots() -> None:
    skeleton = _schema_as_instruction(_Turn.model_json_schema())
    assert isinstance(skeleton, dict)
    assert skeleton["intent"] == "<approve|other>"
    assert skeleton["certain"] == "<true|false>"
    assert skeleton["supplier_names"] == ["<string>"]


def test_the_original_schema_is_untouched() -> None:
    """It is still the validation contract — this only changes what is shown."""
    original = _Decision.model_json_schema()
    _schema_as_instruction(original)
    assert original["properties"]["decision"]["default"] == "none"
    assert original["title"] == "_Decision"


def test_a_schema_without_properties_degrades_to_one_slot() -> None:
    assert _schema_as_instruction({"type": "string"}) == "<string>"
    assert _schema_as_instruction("not a schema") == "not a schema"


def test_a_nested_model_is_rendered_as_a_nested_object() -> None:
    """The one that stopped a demo mid-take.

    ``addendum`` arrives as an ``anyOf`` of a ``$ref`` and ``null``. Rendered
    as a flat string slot it instructs the model to answer with a string, and
    the model obliges — so ``slots``, ``addendum`` and ``submission`` came back
    as prose and every turn failed validation.
    """
    skeleton = _schema_as_instruction(_Turn.model_json_schema())
    assert isinstance(skeleton, dict)
    assert skeleton["addendum"] == {
        "change_summary": "<string>",
        "extend_bids_by_days": "<số, hoặc null>",
    }


def test_a_null_means_absent_not_a_value() -> None:
    """Without a decoding constraint, "not applicable" is written as null.

    ``AddendumRequest.change_summary`` is a plain ``str`` with a default, so a
    literal null fails validation while an absent key does not — and absent is
    what the model meant.
    """
    assert _drop_nulls(
        {
            "intent": "create_request",
            "target_ref": None,
            "addendum": {"change_summary": None, "impact_summary": "x"},
            "supplier_names": ["FPT", None],
        }
    ) == {
        "intent": "create_request",
        "addendum": {"impact_summary": "x"},
        "supplier_names": ["FPT"],
    }
