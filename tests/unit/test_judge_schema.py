"""Unit tests for `debate_gpt.schemas.RoundScore`.

`RoundScore` is the structured-output contract the judge must satisfy
on every call. We test:

  * Happy path: a fully valid payload round-trips.
  * Out-of-range scores: each of the six 0..10 fields rejects <0 and >10.
  * The `mode="before"` validator coerces string-encoded ints ("7")
    and float-encoded ints (7.0) but rejects:
      - bool (True/False must NOT silently become 1/0)
      - non-numeric strings ("abc")
      - non-integer floats (7.5)
      - empty strings
  * `round_winner` is a Literal[A, B, tie] — anything else is rejected.
  * `reasoning` is length-bounded (1..1500).
  * `extra="forbid"` rejects stray fields the LLM might add.
  * The model can be constructed from the public-facing fields only
    (the judge never sees pro/con labels).
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from debate_gpt.schemas import RoundScore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _valid_score(**overrides) -> dict:
    base = {
        "speaker_a_logic": 7,
        "speaker_a_evidence": 6,
        "speaker_a_persuasion": 5,
        "speaker_b_logic": 8,
        "speaker_b_evidence": 7,
        "speaker_b_persuasion": 6,
        "round_winner": "A",
        "reasoning": "A was more concrete.",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_valid_score_round_trips():
    s = RoundScore(**_valid_score())
    assert s.speaker_a_logic == 7
    assert s.speaker_b_persuasion == 6
    assert s.round_winner == "A"
    assert s.reasoning == "A was more concrete."


def test_valid_score_with_min_and_max_boundary_values():
    """0 and 10 are inclusive per PRD §3.5."""
    s_min = RoundScore(**_valid_score(
        speaker_a_logic=0, speaker_a_evidence=0, speaker_a_persuasion=0,
        speaker_b_logic=0, speaker_b_evidence=0, speaker_b_persuasion=0,
    ))
    s_max = RoundScore(**_valid_score(
        speaker_a_logic=10, speaker_a_evidence=10, speaker_a_persuasion=10,
        speaker_b_logic=10, speaker_b_evidence=10, speaker_b_persuasion=10,
    ))
    assert s_min.speaker_a_logic == 0
    assert s_max.speaker_a_logic == 10


def test_score_accepts_tie_winner():
    s = RoundScore(**_valid_score(round_winner="tie"))
    assert s.round_winner == "tie"


# ---------------------------------------------------------------------------
# Out-of-range rejection (per criterion)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("field", [
    "speaker_a_logic", "speaker_a_evidence", "speaker_a_persuasion",
    "speaker_b_logic", "speaker_b_evidence", "speaker_b_persuasion",
])
def test_score_below_zero_is_rejected(field):
    with pytest.raises(ValidationError):
        RoundScore(**_valid_score(**{field: -1}))


@pytest.mark.parametrize("field", [
    "speaker_a_logic", "speaker_a_evidence", "speaker_a_persuasion",
    "speaker_b_logic", "speaker_b_evidence", "speaker_b_persuasion",
])
def test_score_above_ten_is_rejected(field):
    with pytest.raises(ValidationError):
        RoundScore(**_valid_score(**{field: 11}))


# ---------------------------------------------------------------------------
# mode="before" validator: coerce / reject
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("field", [
    "speaker_a_logic", "speaker_a_evidence", "speaker_a_persuasion",
    "speaker_b_logic", "speaker_b_evidence", "speaker_b_persuasion",
])
def test_score_accepts_string_encoded_int(field):
    """LLMs commonly emit numeric fields as strings ("7")."""
    s = RoundScore(**_valid_score(**{field: "7"}))
    assert getattr(s, field) == 7
    assert isinstance(getattr(s, field), int)


@pytest.mark.parametrize("field", [
    "speaker_a_logic", "speaker_a_evidence", "speaker_a_persuasion",
    "speaker_b_logic", "speaker_b_evidence", "speaker_b_persuasion",
])
def test_score_accepts_float_encoded_int(field):
    s = RoundScore(**_valid_score(**{field: 7.0}))
    assert getattr(s, field) == 7


@pytest.mark.parametrize("field", [
    "speaker_a_logic", "speaker_a_evidence", "speaker_a_persuasion",
    "speaker_b_logic", "speaker_b_evidence", "speaker_b_persuasion",
])
def test_score_rejects_non_integer_float(field):
    """7.5 has no integer representation — reject (don't truncate)."""
    with pytest.raises(ValidationError):
        RoundScore(**_valid_score(**{field: 7.5}))


@pytest.mark.parametrize("field", [
    "speaker_a_logic", "speaker_a_evidence", "speaker_a_persuasion",
    "speaker_b_logic", "speaker_b_evidence", "speaker_b_persuasion",
])
def test_score_rejects_non_numeric_string(field):
    with pytest.raises(ValidationError):
        RoundScore(**_valid_score(**{field: "abc"}))


@pytest.mark.parametrize("field", [
    "speaker_a_logic", "speaker_a_evidence", "speaker_a_persuasion",
    "speaker_b_logic", "speaker_b_evidence", "speaker_b_persuasion",
])
def test_score_rejects_empty_string(field):
    with pytest.raises(ValidationError):
        RoundScore(**_valid_score(**{field: ""}))


@pytest.mark.parametrize("field", [
    "speaker_a_logic", "speaker_a_evidence", "speaker_a_persuasion",
    "speaker_b_logic", "speaker_b_evidence", "speaker_b_persuasion",
])
def test_score_rejects_bool(field):
    """`bool` is an `int` subclass in Python — without an explicit
    guard, `True`/`False` would silently become 1/0. The validator
    must reject."""
    with pytest.raises(ValidationError) as exc_info:
        RoundScore(**_valid_score(**{field: True}))
    msg = str(exc_info.value).lower()
    assert "bool" in msg

    with pytest.raises(ValidationError) as exc_info:
        RoundScore(**_valid_score(**{field: False}))
    assert "bool" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# round_winner Literal
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["PRO", "con", "a", "b", "Tie", "PRO/CON", "winner", "", 1, None])
def test_round_winner_rejects_non_literal(bad):
    with pytest.raises(ValidationError):
        RoundScore(**_valid_score(round_winner=bad))


# ---------------------------------------------------------------------------
# reasoning length bounds
# ---------------------------------------------------------------------------

def test_reasoning_must_be_nonempty():
    with pytest.raises(ValidationError):
        RoundScore(**_valid_score(reasoning=""))


def test_reasoning_at_max_length_is_accepted():
    s = RoundScore(**_valid_score(reasoning="x" * 1500))
    assert len(s.reasoning) == 1500


def test_reasoning_over_max_length_is_rejected():
    with pytest.raises(ValidationError):
        RoundScore(**_valid_score(reasoning="x" * 1501))


# ---------------------------------------------------------------------------
# extra="forbid"
# ---------------------------------------------------------------------------

def test_extra_fields_are_rejected():
    """Per schemas.py docstring, `extra="forbid"` rejects stray
    fields the LLM might add (e.g. 'commentary', 'confidence')."""
    with pytest.raises(ValidationError):
        RoundScore(**_valid_score(extra_field="surprise"))


def test_extra_fields_with_pro_or_con_labels_are_rejected():
    """The judge prompt never asks for pro/con, but if the LLM
    hallucinates them the schema must reject — these are the fields
    that would leak position-label bias into persisted scores."""
    with pytest.raises(ValidationError):
        RoundScore(**_valid_score(pro_score=20))
    with pytest.raises(ValidationError):
        RoundScore(**_valid_score(con_score=20))
    with pytest.raises(ValidationError):
        RoundScore(**_valid_score(pro_argument="leaked"))


# ---------------------------------------------------------------------------
# Verdict translation pattern (Speaker A/B → pro/con)
# ---------------------------------------------------------------------------

def test_score_fields_only_reference_speaker_labels_not_pro_con():
    """A regression guard: the public model fields must only be
    speaker_a_* / speaker_b_* / round_winner. `pro_score` / `con_score`
    are computed downstream in `verdict.py`, not on the schema."""
    s = RoundScore(**_valid_score())
    fields = set(s.model_dump().keys())
    # Exactly these 8 fields should be present.
    assert fields == {
        "speaker_a_logic",
        "speaker_a_evidence",
        "speaker_a_persuasion",
        "speaker_b_logic",
        "speaker_b_evidence",
        "speaker_b_persuasion",
        "round_winner",
        "reasoning",
    }
    assert "pro_score" not in fields
    assert "con_score" not in fields
