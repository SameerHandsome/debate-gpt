"""Background debate runner.

Invoked from FastAPI's `BackgroundTasks` (which runs sync callables in a
thread pool — see api.py). The runtime drives the graph round-by-round
itself rather than calling `graph.stream()` or `graph.invoke()`: doing
so lets us interleave streaming-token XADDs with the judge call, which
LangGraph's iterator API makes awkward.

Event flow (per PRD §5.2):
  pro_token* → con_token* → judge_score → pro_token* → ... → verdict

The session_id == debate_id (a single UUID4 generated at POST time);
the Redis stream key (`debate:stream:{id}`) and the DB row share it.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from langchain_core.messages import AIMessage

from . import db, redis_stream
from .agents import build_llms, make_judge_node, make_pro_node, make_con_node
from .prompts import build_con_messages, build_judge_messages, build_pro_messages
from .verdict import tally

logger = logging.getLogger(__name__)


# How many rounds the runtime will attempt. The API caps user input
# between 2 and 5; the runtime trusts whatever it's given (defense in
# depth: cap here too).
_MIN_ROUNDS = 2
_MAX_ROUNDS = 5


def _xadd_json(session_id: str, event: str, round_no: int, payload: Any) -> None:
    """XADD with a JSON-encoded content field. Logs and continues on failure.

    We never want a Redis outage to crash the debate mid-flight. The
    /health endpoint will already show the dependency as degraded.
    """
    try:
        redis_stream.xadd(
            session_id,
            {
                "event": event,
                "round": str(round_no),
                "content": json.dumps(payload, default=str),
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "xadd failed (event=%s round=%s): %s", event, round_no, exc
        )


def _xadd_text(session_id: str, event: str, round_no: int, content: str) -> None:
    """XADD with a plain-text content field (used for pro_token / con_token)."""
    try:
        redis_stream.xadd(
            session_id,
            {"event": event, "round": str(round_no), "content": content},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "xadd failed (event=%s round=%s): %s", event, round_no, exc
        )


def _run_pro_con_round(
    llms: dict[str, Any],
    state: dict[str, Any],
    round_no: int,
    rounds_persisted: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Drive pro → con for one round, XADD-ing tokens, and return the
    judge node's partial result dict (round_scores, round increment).

    `rounds_persisted` is mutated in place with a row ready for the
    `complete_debate` DB write.
    """
    # pro
    pro_messages = build_pro_messages(state)
    pro_text_chunks: list[str] = []
    for chunk in llms["pro"].stream(pro_messages):
        text = _extract(chunk)
        if not text:
            continue
        pro_text_chunks.append(text)
        _xadd_text(state["session_id"], "pro_token", round_no, text)
    pro_text = "".join(pro_text_chunks)

    # con
    con_messages = build_con_messages({**state, "messages": list(state.get("messages", [])) + [
        AIMessage(content=pro_text, name="Pro")
    ]})
    con_text_chunks: list[str] = []
    for chunk in llms["con"].stream(con_messages):
        text = _extract(chunk)
        if not text:
            continue
        con_text_chunks.append(text)
        _xadd_text(state["session_id"], "con_token", round_no, text)
    con_text = "".join(con_text_chunks)

    # judge
    judge_fn = make_judge_node(llms["judge"])
    judge_state = {
        **state,
        "messages": list(state.get("messages", [])) + [
            AIMessage(content=pro_text, name="Pro"),
            AIMessage(content=con_text, name="Con"),
        ],
    }
    result = judge_fn(judge_state)
    score = result["round_scores"][0]

    _xadd_json(state["session_id"], "judge_score", round_no, score)

    rounds_persisted.append(
        {
            "round_number": round_no,
            "pro": pro_text,
            "con": con_text,
            "score": score,
            "winner": score.get("round_winner", "tie"),
        }
    )
    return result


def _extract(chunk: Any) -> str:
    """Normalize a streamed chunk (AIMessageChunk | str | dict) to text."""
    if chunk is None:
        return ""
    if isinstance(chunk, str):
        return chunk
    content = getattr(chunk, "content", None)
    if content is None:
        return ""
    if isinstance(content, list):
        return "".join(
            (p.get("text", "") if isinstance(p, dict) else str(p))
            for p in content
        )
    return str(content)


def run_debate_streaming(session_id: uuid.UUID, topic: str, max_rounds: int) -> None:
    """Background-task entry point. Never raises — logs and marks the
    debate as 'error' on failure.
    """
    max_rounds = max(_MIN_ROUNDS, min(_MAX_ROUNDS, int(max_rounds)))
    session_id_str = str(session_id)

    logger.info(
        "runtime start session=%s topic=%r rounds=%d",
        session_id_str, topic, max_rounds,
    )

    try:
        llms = build_llms()
    except Exception as exc:  # noqa: BLE001
        logger.exception("runtime: failed to build LLMs: %s", exc)
        db.fail_debate_sync(session_id)
        return

    state: dict[str, Any] = {
        "session_id": session_id_str,
        "topic": topic,
        "position_pro": f"For: {topic}",
        "position_con": f"Against: {topic}",
        "round": 1,
        "max_rounds": max_rounds,
        "messages": [],
        "round_scores": [],
        "winner": None,
        "trace_id": None,
    }

    rounds_persisted: list[dict[str, Any]] = []
    try:
        for round_no in range(1, max_rounds + 1):
            state["round"] = round_no
            result = _run_pro_con_round(llms, state, round_no, rounds_persisted)
            if result is None:
                # _run_pro_con_round should never return None in practice
                # (the judge is the only path that can fail mid-round, and
                # it raises on a hard error). Defensive break.
                logger.warning("runtime: round %d returned no result", round_no)
                break
            # Carry forward accumulated state for the next round.
            state["messages"] = list(state.get("messages", [])) + [
                m for m in result.get("messages", [])
            ] if "messages" in result else state.get("messages", [])
            state["round_scores"] = state.get("round_scores", []) + result["round_scores"]
            state["round"] = result.get("round", round_no + 1)
    except Exception as exc:  # noqa: BLE001
        logger.exception("runtime: debate failed mid-flight: %s", exc)
        try:
            _xadd_json(session_id_str, "error", 0, {"message": str(exc)})
        except Exception:  # noqa: BLE001
            pass
        db.fail_debate_sync(session_id)
        return

    # Final tally
    verdict = tally(state["round_scores"])
    _xadd_json(session_id_str, "verdict", 0, verdict)
    logger.info(
        "runtime done session=%s pro_total=%d con_total=%d winner=%s",
        session_id_str, verdict["pro_total"], verdict["con_total"], verdict["winner"],
    )

    # Persist to DB
    try:
        db.complete_debate_sync(
            session_id,
            winner=verdict["winner"],
            rounds=rounds_persisted,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("runtime: failed to persist debate: %s", exc)
        db.fail_debate_sync(session_id)
