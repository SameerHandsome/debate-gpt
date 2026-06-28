"""Pydantic schemas for structured LLM outputs.

Day 1 imports RoundScore lightly for a single shape-check inside the judge
node. Full range validation, retries, and eval hooks land Day 2.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RoundScore(BaseModel):
    """Per PRD §3.5. The judge returns one of these each round."""

    speaker_a_logic: int = Field(ge=0, le=10)
    speaker_a_evidence: int = Field(ge=0, le=10)
    speaker_a_persuasion: int = Field(ge=0, le=10)
    speaker_b_logic: int = Field(ge=0, le=10)
    speaker_b_evidence: int = Field(ge=0, le=10)
    speaker_b_persuasion: int = Field(ge=0, le=10)
    round_winner: Literal["A", "B", "tie"]
    reasoning: str