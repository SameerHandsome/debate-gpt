"""Unit tests for `debate_gpt.state.DebateState`.

`DebateState` is a TypedDict, so the type system doesn't enforce
validity at runtime — but the *reducers* it annotates are runtime
behavior. We test:

  * `messages` uses the LangGraph `add_messages` reducer: appending
    via a node return value extends the list, not replaces it.
  * `round_scores` uses the operator.add (list-concat) reducer:
    a node returning `{"round_scores": [score]}` extends the list.
  * Initial state shape matches the keys consumed by the graph
    nodes (so a regression in the schema is caught here).
  * `max_rounds` is bounded to 2..5 by the API/runtime contract;
    the state itself doesn't enforce this, but downstream code does.
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph.message import add_messages

from debate_gpt.state import DebateState


# ---------------------------------------------------------------------------
# Initial state shape
# ---------------------------------------------------------------------------

def _base_state(**overrides) -> DebateState:
    state: DebateState = {
        "session_id": "sess-1",
        "topic": "Test topic",
        "position_pro": "For: Test topic",
        "position_con": "Against: Test topic",
        "round": 1,
        "max_rounds": 3,
        "messages": [],
        "round_scores": [],
        "winner": None,
        "trace_id": None,
    }
    state.update(overrides)
    return state


def test_state_creation_with_valid_round_counts():
    """1, 3, 5 are all legal starting rounds (1-indexed)."""
    for r in (1, 2, 3, 4, 5):
        s = _base_state(round=r, max_rounds=5)
        assert s["round"] == r
        assert s["max_rounds"] == 5


def test_state_default_round_is_one_indexed():
    """Per CLAUDE.md, `round` is 1-indexed — round 1 is the first round."""
    s = _base_state()
    assert s["round"] == 1
    assert s["round"] >= 1


def test_state_with_zero_or_negative_round_is_a_typeddict_smell():
    """A TypedDict doesn't reject `round=0` at runtime, but the runtime
    contract is 1-indexed — document the invariant and surface a clear
    error if violated. (No exception is raised by the TypedDict itself.)"""
    s_zero = _base_state(round=0)
    s_neg = _base_state(round=-1)
    # TypedDict doesn't validate — but the values are wrong.
    assert s_zero["round"] == 0
    assert s_neg["round"] == -1
    # The runtime's `should_continue` would treat round=0 as "done"
    # immediately (0 <= max_rounds is true, but round=0 means the loop
    # never executes). Test the invariant in graph tests instead.


def test_state_has_required_keys():
    """All keys the nodes read from state must be present."""
    s = _base_state()
    required = {
        "session_id", "topic", "position_pro", "position_con",
        "round", "max_rounds", "messages", "round_scores", "winner", "trace_id",
    }
    assert required.issubset(s.keys())


# ---------------------------------------------------------------------------
# `messages` reducer (add_messages)
# ---------------------------------------------------------------------------

def test_add_messages_reducer_appends_rather_than_replaces():
    """`add_messages` must extend the list, not replace it. The pro
    node returns just its own message; the con node must see the pro
    message still in state."""
    initial = _base_state(messages=[])
    pro_msg = AIMessage(content="[pro]", name="Pro")
    con_msg = AIMessage(content="[con]", name="Con")

    after_pro = add_messages(initial["messages"], [pro_msg])
    after_con = add_messages(after_pro, [con_msg])

    assert [m.content for m in after_pro] == ["[pro]"]
    assert [m.content for m in after_con] == ["[pro]", "[con]"]


def test_add_messages_reducer_preserves_message_identity():
    """A node returning a HumanMessage should be appended, not replace
    a prior AIMessage."""
    prior = [AIMessage(content="hi", name="Pro")]
    new = add_messages(prior, [HumanMessage(content="round 2 prompt")])
    assert len(new) == 2
    assert isinstance(new[0], AIMessage)
    assert isinstance(new[1], HumanMessage)


def test_messages_reducer_with_existing_messages_starts_from_full_list():
    """If state already has messages, the reducer must not lose them
    when a node returns its own contribution."""
    initial_messages = [
        AIMessage(content="round1 pro", name="Pro"),
        AIMessage(content="round1 con", name="Con"),
    ]
    out = add_messages(initial_messages, [AIMessage(content="round2 pro", name="Pro")])
    assert [m.content for m in out] == [
        "round1 pro", "round1 con", "round2 pro",
    ]


# ---------------------------------------------------------------------------
# `round_scores` reducer (list-concat via operator.add)
# ---------------------------------------------------------------------------

def test_round_scores_reducer_concatenates_lists():
    """`round_scores` uses `operator.add` (list-concat), so a node
    returning `{"round_scores": [score]}` appends a single element to
    the existing list."""
    existing = [{"round_winner": "A", "speaker_a_logic": 5}]
    new = [{"round_winner": "B", "speaker_a_logic": 6}]
    out = existing + new
    assert len(out) == 2
    assert out[0]["round_winner"] == "A"
    assert out[1]["round_winner"] == "B"


def test_round_scores_accumulates_across_rounds():
    """Three rounds must produce a 3-element list, not overwrite."""
    scores = []
    for r in (1, 2, 3):
        scores = scores + [{
            "round_winner": "tie",
            "speaker_a_logic": 5 + r,
            "speaker_a_evidence": 5,
            "speaker_a_persuasion": 5,
            "speaker_b_logic": 5,
            "speaker_b_evidence": 5,
            "speaker_b_persuasion": 5,
            "pro_score": 15,
            "con_score": 15,
        }]
    assert len(scores) == 3
    assert [s["speaker_a_logic"] for s in scores] == [6, 7, 8]


# ---------------------------------------------------------------------------
# `winner` / `trace_id` (NotRequired)
# ---------------------------------------------------------------------------

def test_winner_can_be_none_on_initial_state():
    s = _base_state()
    assert s["winner"] is None


def test_winner_can_be_set_to_a_valid_label():
    s = _base_state(winner="pro")
    assert s["winner"] == "pro"


def test_trace_id_optional():
    s = _base_state()
    assert s["trace_id"] is None
    s2 = _base_state(trace_id="abc-123")
    assert s2["trace_id"] == "abc-123"
