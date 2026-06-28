"""Debate graph state definition.

Per PRD §3.3. `round` is the 1-indexed round currently being argued; the
judge node increments it to N+1 after scoring round N, and the conditional
edge reads the post-increment value to decide whether to loop.

`messages` and `round_scores` are annotated with reducers so that
sequential nodes accumulate their contributions rather than overwriting
the previous node's output. `messages` uses LangGraph's `add_messages`
reducer; `round_scores` uses a custom list-concat reducer.
"""

from __future__ import annotations

from operator import add
from typing import Annotated, NotRequired

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class DebateState(TypedDict):
    session_id: str
    topic: str
    position_pro: str
    position_con: str
    round: int
    max_rounds: int
    messages: Annotated[list[BaseMessage], add_messages]
    round_scores: Annotated[list[dict], add]
    winner: NotRequired[str | None]
    trace_id: NotRequired[str | None]