"""Verdict aggregation.

Pure functions over `round_scores` (the per-round dicts produced by the
judge node). Lives in its own module so both `agents.py` (which emits
per-round totals during scoring) and the Day-3 runtime (which finalizes
the debate winner) can share the math without a circular import.

`winner` rule (Day 3 default — see plan):
- Sum `pro_score` and `con_score` across all rounds.
- Higher total wins; equal totals = `tie`.
"""
from __future__ import annotations

from typing import TypedDict


class Verdict(TypedDict):
    pro_total: int
    con_total: int
    winner: str  # "pro" | "con" | "tie"


def pro_total_for_round(score: dict, swap: bool) -> int:
    """Sum Pro's three criteria for a single round.

    swap=True (even rounds): Con was Speaker A, Pro was Speaker B.
    swap=False (odd rounds): Pro was Speaker A, Con was Speaker B.
    """
    if swap:
        return (
            score["speaker_b_logic"]
            + score["speaker_b_evidence"]
            + score["speaker_b_persuasion"]
        )
    return (
        score["speaker_a_logic"]
        + score["speaker_a_evidence"]
        + score["speaker_a_persuasion"]
    )


def con_total_for_round(score: dict, swap: bool) -> int:
    if swap:
        return (
            score["speaker_a_logic"]
            + score["speaker_a_evidence"]
            + score["speaker_a_persuasion"]
        )
    return (
        score["speaker_b_logic"]
        + score["speaker_b_evidence"]
        + score["speaker_b_persuasion"]
    )


def tally(round_scores: list[dict]) -> Verdict:
    """Sum totals across rounds; pick winner or tie."""
    pro_total = 0
    con_total = 0
    for score in round_scores:
        # The judge node already stores `pro_score` / `con_score` on the
        # per-round dict (Day 2). Prefer those so we don't need to know
        # the swap flag here.
        pro_total += int(score.get("pro_score", 0))
        con_total += int(score.get("con_score", 0))

    if pro_total > con_total:
        winner = "pro"
    elif con_total > pro_total:
        winner = "con"
    else:
        winner = "tie"
    return Verdict(pro_total=pro_total, con_total=con_total, winner=winner)
