"""Dry-run the graph with fake LLMs. Verifies topology, round counting,
and conditional edge behavior without touching the real APIs.

Run with:  python dry_run.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from langchain_core.messages import AIMessage  # noqa: E402

from debate_gpt.graph import build_graph  # noqa: E402
from debate_gpt.state import DebateState  # noqa: E402


class FakeLLM:
    """Minimal stub that returns canned text. Cycles between 'pro' and 'con'
    personas based on system message content, and emits a valid JSON scorecard
    for the judge."""

    n_pro_calls = 0
    n_con_calls = 0
    n_judge_calls = 0

    def invoke(self, messages):
        from langchain_core.messages import SystemMessage  # local import
        sys_msg = next((m for m in messages if isinstance(m, SystemMessage)), None)
        role = sys_msg.content[:20] if sys_msg else ""
        if "FOR the motion" in (sys_msg.content if sys_msg else ""):
            FakeLLM.n_pro_calls += 1
            return AIMessage(content=f"[fake pro #{FakeLLM.n_pro_calls}]", name="Pro")
        if "AGAINST the motion" in (sys_msg.content if sys_msg else ""):
            FakeLLM.n_con_calls += 1
            return AIMessage(content=f"[fake con #{FakeLLM.n_con_calls}]", name="Con")
        if "impartial debate judge" in (sys_msg.content if sys_msg else ""):
            FakeLLM.n_judge_calls += 1
            return AIMessage(content=(
                '{"speaker_a_logic":7,"speaker_a_evidence":6,'
                '"speaker_a_persuasion":5,"speaker_b_logic":7,'
                '"speaker_b_evidence":6,"speaker_b_persuasion":5,'
                '"round_winner":"tie","reasoning":"balanced"}'
            ), name="Judge")
        raise RuntimeError(f"FakeLLM got unexpected system prompt: {role!r}")


def main() -> int:
    initial: DebateState = {
        "session_id": "test",
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

    # Monkeypatch: build_graph() instantiates real LLMs via load_settings();
    # we bypass that by calling make_*_node directly with FakeLLM and wiring
    # a fresh StateGraph in-process.
    from langgraph.graph import END, START, StateGraph  # noqa: PLC0415
    from debate_gpt.agents import make_con_node, make_judge_node, make_pro_node  # noqa: PLC0415

    fake = FakeLLM()
    g = StateGraph(DebateState)
    g.add_node("pro_node", make_pro_node(fake))
    g.add_node("con_node", make_con_node(fake))
    g.add_node("judge_node", make_judge_node(fake))
    g.add_edge(START, "pro_node")
    g.add_edge("pro_node", "con_node")
    g.add_edge("con_node", "judge_node")
    from debate_gpt.graph import should_continue  # noqa: PLC0415
    g.add_conditional_edges("judge_node", should_continue,
                            {"pro_node": "pro_node", END: END})
    compiled = g.compile()

    final = compiled.invoke(initial)

    print(f"pro calls    = {FakeLLM.n_pro_calls}")
    print(f"con calls    = {FakeLLM.n_con_calls}")
    print(f"judge calls  = {FakeLLM.n_judge_calls}")
    print(f"messages     = {len(final['messages'])}")
    print(f"round_scores = {len(final['round_scores'])}")
    print(f"final round  = {final['round']}")
    print(f"round_scores[0] keys = {sorted(final['round_scores'][0].keys())}")

    expected_pro = expected_con = expected_judge = 3
    assert FakeLLM.n_pro_calls == expected_pro, f"pro calls {FakeLLM.n_pro_calls}"
    assert FakeLLM.n_con_calls == expected_con, f"con calls {FakeLLM.n_con_calls}"
    assert FakeLLM.n_judge_calls == expected_judge, f"judge calls {FakeLLM.n_judge_calls}"
    assert len(final["messages"]) == 6, f"messages {len(final['messages'])}"
    assert len(final["round_scores"]) == 3, f"round_scores {len(final['round_scores'])}"
    assert final["round"] == 4, f"final round {final['round']}"  # 3 + 1
    assert final["round_scores"][0]["round_winner"] == "tie"
    print("\nDry-run OK — 3 rounds, 6 messages, 3 scorecards, final round=4.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())