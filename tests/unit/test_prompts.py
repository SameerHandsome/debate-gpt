"""Unit tests for `debate_gpt.prompts`.

The bias-mitigation invariant (PRD §3.4, enforced by Day 6's eval
suite) is: the judge **never** sees the words "Pro" or "Con" — only
"Speaker A" and "Speaker B". We test that invariant directly.

We also test that the Pro and Con builders each render a system +
human message pair containing the topic, round, and the agent's own
position string (so a regression in prompt construction is caught
without hitting the real LLM).
"""
from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from debate_gpt.prompts import (
    build_con_messages,
    build_judge_messages,
    build_pro_messages,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _state(round_no: int = 1, max_rounds: int = 3, swap: bool = False) -> dict:
    return {
        "session_id": "sess",
        "topic": "Social media should be regulated as a public utility",
        "position_pro": "For: Social media should be regulated as a public utility",
        "position_con": "Against: Social media should be regulated as a public utility",
        "round": round_no,
        "max_rounds": max_rounds,
        "messages": [],
        "round_scores": [],
        "winner": None,
        "trace_id": None,
    }


# ---------------------------------------------------------------------------
# Pro
# ---------------------------------------------------------------------------

def test_pro_messages_have_system_and_human_pair():
    msgs = build_pro_messages(_state())
    assert len(msgs) == 2
    assert isinstance(msgs[0], SystemMessage)
    assert isinstance(msgs[1], HumanMessage)


def test_pro_system_prompt_mentions_for_the_motion():
    msgs = build_pro_messages(_state())
    assert "FOR the motion" in msgs[0].content


def test_pro_human_prompt_carries_topic_and_position():
    msgs = build_pro_messages(_state(round_no=2, max_rounds=5))
    human = msgs[1].content
    assert "Social media" in human
    assert "Round: 2 of 5" in human
    assert "For: Social media" in human


def test_pro_human_prompt_does_not_leak_con_position():
    """Even though the state has a `position_con`, the pro prompt
    should not surface it (the pro doesn't know the con's stance)."""
    msgs = build_pro_messages(_state())
    assert "Against:" not in msgs[1].content


# ---------------------------------------------------------------------------
# Con
# ---------------------------------------------------------------------------

def test_con_messages_have_system_and_human_pair():
    msgs = build_con_messages(_state())
    assert len(msgs) == 2
    assert isinstance(msgs[0], SystemMessage)
    assert isinstance(msgs[1], HumanMessage)


def test_con_system_prompt_mentions_against_the_motion():
    msgs = build_con_messages(_state())
    assert "AGAINST the motion" in msgs[0].content


def test_con_human_prompt_carries_con_position():
    msgs = build_con_messages(_state(round_no=3, max_rounds=5))
    human = msgs[1].content
    assert "Round: 3 of 5" in human
    assert "Against: Social media" in human


def test_con_human_prompt_does_not_leak_pro_position():
    msgs = build_con_messages(_state())
    assert "For:" not in msgs[1].content


# ---------------------------------------------------------------------------
# Judge — the bias-mitigation invariant
# ---------------------------------------------------------------------------

PRO_TEXT = "Pro: regulation prevents harm."
CON_TEXT = "Con: regulation stifles innovation."


def test_judge_messages_have_system_and_human_pair():
    bundle = build_judge_messages(_state(), PRO_TEXT, CON_TEXT, swap=False)
    assert len(bundle.messages) == 2
    assert isinstance(bundle.messages[0], SystemMessage)
    assert isinstance(bundle.messages[1], HumanMessage)


def test_judge_system_prompt_mentions_speaker_a_and_speaker_b():
    """The system prompt must teach the model to think in terms of
    A/B, not pro/con."""
    bundle = build_judge_messages(_state(), PRO_TEXT, CON_TEXT, swap=False)
    sys_text = bundle.messages[0].content
    assert "Speaker A" in sys_text
    assert "Speaker B" in sys_text
    # Critical: no "Pro" / "Con" labels in the system prompt.
    # We check for the standalone words so we don't false-positive on
    # e.g. "pro/con" substrings in explanatory text.
    for forbidden in ("Pro side", "Con side", "For the motion", "Against the motion"):
        assert forbidden not in sys_text, f"judge system prompt contains {forbidden!r}"


def test_judge_human_prompt_uses_speaker_a_and_speaker_b_labels():
    """Round-1 (no swap): Pro text is labeled Speaker A, Con text is
    labeled Speaker B. The string 'Pro' and 'Con' must not appear
    in the user payload."""
    bundle = build_judge_messages(_state(), PRO_TEXT, CON_TEXT, swap=False)
    human = bundle.messages[1].content
    assert "--- Speaker A ---" in human
    assert "--- Speaker B ---" in human
    assert PRO_TEXT in human
    assert CON_TEXT in human
    # The labels in the prompt must not be "Pro" / "Con".
    assert "--- Pro ---" not in human
    assert "--- Con ---" not in human


def test_judge_human_prompt_swaps_labels_on_even_rounds():
    """Round-2 (swap=True): Pro text is labeled Speaker B, Con text
    is labeled Speaker A. The 'Speaker A' block must contain the
    con text, and vice versa."""
    bundle = build_judge_messages(_state(round_no=2), PRO_TEXT, CON_TEXT, swap=True)
    human = bundle.messages[1].content
    # Extract the two blocks
    a_idx = human.index("--- Speaker A ---")
    b_idx = human.index("--- Speaker B ---")
    a_block = human[a_idx:b_idx]
    b_block = human[b_idx:]
    # A block (which is Con text) should NOT contain "Pro: regulation"
    assert "Pro: regulation prevents harm" not in a_block
    # B block (which is Pro text) should NOT contain "Con: regulation"
    assert "Con: regulation stifles innovation" not in b_block


def test_judge_bundle_exposes_pro_label_for_logging():
    """The bundle's `pro_label` / `con_label` are exposed for logging
    so the runtime can record which speaker the model saw as Pro.
    On odd rounds, Pro = Speaker A; on even rounds, Pro = Speaker B."""
    odd = build_judge_messages(_state(round_no=1), PRO_TEXT, CON_TEXT, swap=False)
    even = build_judge_messages(_state(round_no=2), PRO_TEXT, CON_TEXT, swap=True)
    assert odd.pro_label == "Speaker A"
    assert odd.con_label == "Speaker B"
    assert even.pro_label == "Speaker B"
    assert even.con_label == "Speaker A"


def test_judge_prompt_carries_topic_and_round_metadata():
    """The judge needs context to evaluate — topic + round number
    are part of the payload."""
    bundle = build_judge_messages(
        _state(round_no=2, max_rounds=5),
        PRO_TEXT, CON_TEXT, swap=True,
    )
    human = bundle.messages[1].content
    assert "Topic under debate: Social media" in human
    assert "Round: 2 of 5" in human


@pytest.mark.parametrize("swap", [False, True])
def test_judge_payload_never_uses_word_pro_or_con_as_label(swap):
    """The strongest version of the bias-mitigation invariant:
    the words 'Pro' and 'Con' (capitalized, as labels) must never
    appear as section labels in the judge payload."""
    bundle = build_judge_messages(_state(round_no=2 if swap else 1), PRO_TEXT, CON_TEXT, swap=swap)
    human = bundle.messages[1].content
    assert "--- Pro ---" not in human
    assert "--- Con ---" not in human
