"""Pydantic schemas for structured LLM outputs.

Day 2: RoundScore is locked down. `extra="forbid"` rejects stray fields the
LLM might add; the `mode="before"` validator coerces common LLM typos like
string-encoded ints (`"7"`) or float-encoded ints (`7.0`) but rejects booleans
and non-numeric strings. `reasoning` is length-bounded to keep a runaway
response from poisoning the graph.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


_INT_0_10 = Field(ge=0, le=10)


class RoundScore(BaseModel):
    """Per PRD §3.5. The judge returns one of these each round."""

    model_config = ConfigDict(extra="forbid")

    speaker_a_logic: int = _INT_0_10
    speaker_a_evidence: int = _INT_0_10
    speaker_a_persuasion: int = _INT_0_10
    speaker_b_logic: int = _INT_0_10
    speaker_b_evidence: int = _INT_0_10
    speaker_b_persuasion: int = _INT_0_10
    round_winner: Literal["A", "B", "tie"]
    reasoning: str = Field(min_length=1, max_length=1500)

    @field_validator(
        "speaker_a_logic",
        "speaker_a_evidence",
        "speaker_a_persuasion",
        "speaker_b_logic",
        "speaker_b_evidence",
        "speaker_b_persuasion",
        mode="before",
    )
    @classmethod
    def _coerce_score(cls, v):
        # `bool` is a subclass of `int` in Python; reject it explicitly so
        # `True`/`False` cannot silently become 1/0.
        if isinstance(v, bool):
            raise ValueError("score must be an integer 0-10, not a bool")
        if isinstance(v, str):
            v = v.strip()
            if not v:
                raise ValueError("score is an empty string")
            # Raises ValueError on "abc" — caught by the retry helper and
            # fed back to the model.
            v = int(v)
        if isinstance(v, float):
            if not v.is_integer():
                raise ValueError(f"score must be an integer, got {v}")
            v = int(v)
        return v
