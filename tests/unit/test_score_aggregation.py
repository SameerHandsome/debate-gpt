"""Unit tests for `debate_gpt.verdict` — tally & per-round totals.

`verdict.py` is pure functions over the per-round dicts the judge
node emits. Two surfaces:

  * `pro_total_for_round(score, swap)` /
    `con_total_for_round(score, swap)` — sum the three criteria for
    the right speaker, given the swap flag (odd rounds: Pro = A;
    even rounds: Pro = B).

  * `tally(round_scores)` — sum `pro_score` / `con_score` across
    rounds; declare "pro", "con", or "tie".

We test both, and the *interaction* — that running the totals
through `tally` matches what `tally` would compute by reading the
precomputed `pro_score` / `con_score` fields directly.
"""
from __future__ import annotations

import pytest

from debate_gpt.verdict import (
    Verdict,
    con_total_for_round,
    pro_total_for_round,
    tally,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _round(a: tuple[int, int, int], b: tuple[int, int, int], winner: str = "A",
           pro_score: int | None = None, con_score: int | None = None) -> dict:
    """Build a per-round score dict.

    `a` is (logic, evidence, persuasion) for Speaker A;
    `b` is the same for Speaker B. Optional `pro_score` / `con_score`
    simulate the post-swap totals the judge node computes and stores
    on the dict.
    """
    d = {
        "speaker_a_logic": a[0],
        "speaker_a_evidence": a[1],
        "speaker_a_persuasion": a[2],
        "speaker_b_logic": b[0],
        "speaker_b_evidence": b[1],
        "speaker_b_persuasion": b[2],
        "round_winner": winner,
    }
    if pro_score is not None:
        d["pro_score"] = pro_score
    if con_score is not None:
        d["con_score"] = con_score
    return d


# ---------------------------------------------------------------------------
# pro_total_for_round (swap-aware)
# ---------------------------------------------------------------------------

def test_pro_total_odd_round_pro_is_speaker_a():
    """Round 1, 3, 5: Pro = Speaker A. Sum A's three scores."""
    score = _round((5, 6, 7), (1, 2, 3))  # Pro = 18, Con = 6
    assert pro_total_for_round(score, swap=False) == 5 + 6 + 7


def test_pro_total_even_round_pro_is_speaker_b():
    """Round 2, 4: Pro = Speaker B. Sum B's three scores."""
    score = _round((1, 2, 3), (5, 6, 7))  # Pro = 18, Con = 6
    assert pro_total_for_round(score, swap=True) == 5 + 6 + 7


def test_pro_total_works_when_all_six_scores_differ():
    score = _round((2, 4, 6), (3, 5, 7))  # Pro on even = B = 15
    assert pro_total_for_round(score, swap=False) == 12
    assert pro_total_for_round(score, swap=True) == 15


# ---------------------------------------------------------------------------
# con_total_for_round (swap-aware, complementary)
# ---------------------------------------------------------------------------

def test_con_total_odd_round_con_is_speaker_b():
    score = _round((5, 6, 7), (1, 2, 3))
    assert con_total_for_round(score, swap=False) == 1 + 2 + 3


def test_con_total_even_round_con_is_speaker_a():
    score = _round((5, 6, 7), (1, 2, 3))
    assert con_total_for_round(score, swap=True) == 5 + 6 + 7


def test_pro_plus_con_equals_total_scorecard_sum():
    """A round's Pro total + Con total must equal the sum of all six
    scores, regardless of swap."""
    score = _round((2, 4, 6), (3, 5, 7))
    total = sum(
        score[k] for k in (
            "speaker_a_logic", "speaker_a_evidence", "speaker_a_persuasion",
            "speaker_b_logic", "speaker_b_evidence", "speaker_b_persuasion",
        )
    )
    assert pro_total_for_round(score, swap=False) + con_total_for_round(score, swap=False) == total
    assert pro_total_for_round(score, swap=True) + con_total_for_round(score, swap=True) == total


def test_swap_inverts_pro_and_con_totals():
    """A score where A is high and B is low: on the odd round Pro is
    A (high), on the even round Pro is B (low)."""
    score = _round((9, 9, 9), (3, 3, 3))
    assert pro_total_for_round(score, swap=False) == 27  # Pro = A
    assert con_total_for_round(score, swap=False) == 9   # Con = B
    assert pro_total_for_round(score, swap=True) == 9    # Pro = B
    assert con_total_for_round(score, swap=True) == 27   # Con = A


# ---------------------------------------------------------------------------
# tally() — winner / tie / totals
# ---------------------------------------------------------------------------

def test_tally_with_no_rounds_is_a_tie():
    v = tally([])
    assert v == Verdict(pro_total=0, con_total=0, winner="tie")


def test_tally_sums_pro_score_and_con_score():
    rounds = [
        _round((0, 0, 0), (0, 0, 0), pro_score=20, con_score=15),
        _round((0, 0, 0), (0, 0, 0), pro_score=18, con_score=21),
    ]
    v = tally(rounds)
    assert v["pro_total"] == 38
    assert v["con_total"] == 36
    assert v["winner"] == "pro"


def test_tally_declares_pro_winner():
    rounds = [
        _round((0, 0, 0), (0, 0, 0), pro_score=20, con_score=10),
        _round((0, 0, 0), (0, 0, 0), pro_score=15, con_score=18),
        _round((0, 0, 0), (0, 0, 0), pro_score=25, con_score=20),
    ]
    assert tally(rounds)["winner"] == "pro"


def test_tally_declares_con_winner():
    rounds = [
        _round((0, 0, 0), (0, 0, 0), pro_score=10, con_score=20),
        _round((0, 0, 0), (0, 0, 0), pro_score=15, con_score=18),
    ]
    assert tally(rounds)["winner"] == "con"


def test_tally_declares_tie_when_totals_equal():
    rounds = [
        _round((0, 0, 0), (0, 0, 0), pro_score=20, con_score=20),
        _round((0, 0, 0), (0, 0, 0), pro_score=18, con_score=18),
    ]
    assert tally(rounds) == Verdict(pro_total=38, con_total=38, winner="tie")


def test_tally_ignores_round_winner_field_uses_precomputed_totals():
    """The judge node writes `pro_score` / `con_score` (swap-aware)
    onto the dict; `tally` reads those, not the raw speaker scores.
    If the schema were to ship a dict without precomputed totals,
    `tally` should treat the missing fields as zero — not fall back
    to summing the raw speakers (which would assume Pro=A)."""
    rounds = [
        # No pro_score / con_score set; both default to 0.
        _round((9, 9, 9), (1, 1, 1)),
        _round((9, 9, 9), (1, 1, 1)),
    ]
    v = tally(rounds)
    assert v["pro_total"] == 0
    assert v["con_total"] == 0
    assert v["winner"] == "tie"


def test_tally_coerces_string_totals_to_int():
    """asyncpg returns JSONB values as Python objects; some paths
    may surface ints as strings. `tally` uses `int(score.get(...))`
    and must tolerate this."""
    rounds = [
        _round((0, 0, 0), (0, 0, 0), pro_score="20", con_score="10"),
    ]
    v = tally(rounds)
    assert v["pro_total"] == 20
    assert v["con_total"] == 10
    assert v["winner"] == "pro"


def test_tally_three_rounds_with_mixed_winners():
    rounds = [
        _round((0, 0, 0), (0, 0, 0), pro_score=20, con_score=15),
        _round((0, 0, 0), (0, 0, 0), pro_score=15, con_score=20),
        _round((0, 0, 0), (0, 0, 0), pro_score=18, con_score=18),
    ]
    v = tally(rounds)
    assert v["pro_total"] == 53
    assert v["con_total"] == 53
    assert v["winner"] == "tie"


def test_tally_pro_score_higher_by_one_is_a_pro_win():
    """Boundary: a one-point advantage still wins (not a tie)."""
    rounds = [_round((0, 0, 0), (0, 0, 0), pro_score=20, con_score=19)]
    assert tally(rounds)["winner"] == "pro"
