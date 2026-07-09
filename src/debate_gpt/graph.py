"""LangGraph wiring for the debate graph.

Topology (PRD §3.2, §3.4):

    START -> pro_node -> con_node -> judge_node -> (conditional)
                                                     |
                                            round <= max_rounds ? pro_node : END

`judge_node` increments `round` to N+1 in its return value. The conditional
edge reads the post-increment value, so round 1 -> 2 -> 3 with judge
returning 2, 3, 4; the fourth call exits.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from .agents import ChunkSink, build_llms, make_con_node, make_judge_node, make_pro_node
from .state import DebateState


def should_continue(state: DebateState) -> str:
    """Conditional edge after judge_node. Loop while there are rounds left."""
    if state["round"] <= state["max_rounds"]:
        return "pro_node"
    return END


def build_graph(
    llms: dict[str, Any] | None = None,
    chunk_sink: ChunkSink | None = None,
):
    """Compile the debate graph.

    Parameters
    ----------
    llms : dict, optional
        Override the real LLM clients. Day 5's pytest suite (and
        `dry_run.py`) inject a `FakeLLM` here.
    chunk_sink : callable, optional
        `(event, round, content) -> None` invoked as pro/con tokens
        stream. Day 3's runtime passes a sink that XADDs each chunk to
        the session's Upstash Stream.
    """
    if llms is None:
        llms = build_llms()

    g = StateGraph(DebateState)

    g.add_node("pro_node", make_pro_node(llms["pro"], chunk_sink=chunk_sink))
    g.add_node("con_node", make_con_node(llms["con"], chunk_sink=chunk_sink))
    g.add_node("judge_node", make_judge_node(llms["judge"]))

    g.add_edge(START, "pro_node")
    g.add_edge("pro_node", "con_node")
    g.add_edge("con_node", "judge_node")
    g.add_conditional_edges(
        "judge_node",
        should_continue,
        {"pro_node": "pro_node", END: END},
    )
    return g.compile()