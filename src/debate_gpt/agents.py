"""LLM clients and node factories for the debate graph.

Per PRD §3.4:
- Pro  → Groq `allam-2-7b`, temperature 0.9
- Con  → Groq `llama-3.1-8b-instant`, temperature 0.9
- Judge → OpenRouter `openai/gpt-oss-120b`, temperature 0.2

Each node is built as a factory `(llm) -> node_fn` so Day 5 tests can inject
fake LLMs without monkey-patching globals.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable

from langchain_core.messages import AIMessage
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI

from .config import load_settings
from .prompts import build_con_messages, build_judge_messages, build_pro_messages
from .schemas import RoundScore
from .state import DebateState

logger = logging.getLogger(__name__)


# ---------- LLM clients ----------

def build_llms() -> dict[str, Any]:
    settings = load_settings()

    pro = ChatGroq(
        model="allam-2-7b",
        temperature=0.9,
        api_key=settings["groq_api_key"],
    )
    con = ChatGroq(
        model="llama-3.1-8b-instant",
        temperature=0.9,
        api_key=settings["groq_api_key"],
    )
    judge = ChatOpenAI(
        model="openai/gpt-oss-120b",
        temperature=0.2,
        api_key=settings["openrouter_api_key"],
        base_url="https://openrouter.ai/api/v1",
        default_headers={
            "HTTP-Referer": "https://github.com/SameerHandsome/debate-gpt",
            "X-Title": "debate-gpt",
        },
    )
    return {"pro": pro, "con": con, "judge": judge}


# ---------- Node factories ----------

NodeFn = Callable[[DebateState], dict]


def make_pro_node(llm) -> NodeFn:
    def pro_node(state: DebateState) -> dict:
        messages = build_pro_messages(state)
        response = llm.invoke(messages)
        content = _extract_content(response)
        logger.info("pro round=%d chars=%d", state["round"], len(content))
        return {"messages": [AIMessage(content=content, name="Pro")]}

    return pro_node


def make_con_node(llm) -> NodeFn:
    def con_node(state: DebateState) -> dict:
        messages = build_con_messages(state)
        response = llm.invoke(messages)
        content = _extract_content(response)
        logger.info("con round=%d chars=%d", state["round"], len(content))
        return {"messages": [AIMessage(content=content, name="Con")]}

    return con_node


def make_judge_node(llm) -> NodeFn:
    def judge_node(state: DebateState) -> dict:
        pro_text = _latest_text(state["messages"], name="Pro")
        con_text = _latest_text(state["messages"], name="Con")
        if pro_text is None or con_text is None:
            raise RuntimeError(
                f"judge_node received no Pro/Con arguments "
                f"(round={state['round']}, messages={len(state['messages'])})"
            )

        swap = state["round"] % 2 == 0
        messages = build_judge_messages(state, pro_text, con_text, swap=swap)
        response = llm.invoke(messages)
        raw = _extract_content(response)

        score_dict = _parse_judge_output(raw)
        next_round = state["round"] + 1

        logger.info(
            "judge round=%d swap=%s winner=%s next_round=%d",
            state["round"], swap, score_dict.get("round_winner"), next_round,
        )
        return {
            "round_scores": [score_dict],
            "round": next_round,
        }

    return judge_node


# ---------- Helpers ----------

def _extract_content(response: Any) -> str:
    """Pull the string content out of a chat-model response, regardless of
    whether it returns a string, an AIMessage, or has a `.content` attr."""
    if isinstance(response, str):
        return response
    content = getattr(response, "content", None)
    if content is None:
        raise RuntimeError(f"LLM response had no .content: {response!r}")
    if isinstance(content, list):
        # Some providers return content as a list of parts; join text parts.
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    return str(content)


def _latest_text(messages: list, name: str) -> str | None:
    """Return the most recent AIMessage.content with the given `name`, or None."""
    for msg in reversed(messages):
        if getattr(msg, "name", None) == name:
            return msg.content if isinstance(msg.content, str) else str(msg.content)
    return None


_JSON_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _parse_judge_output(raw: str) -> dict:
    """Best-effort parse of the judge's JSON output.

    Day 1: try strict JSON first, then strip code fences, then keep the raw
    string under `{"raw": ...}` so the CLI never crashes on a malformed
    response. Day 2 adds Pydantic range validation + retry.
    """
    text = raw.strip()
    # Strip ```json ... ``` fences if the model wraps its output.
    text = _JSON_FENCE.sub("", text).strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            # Best-effort schema check; tolerate extra keys, require the
            # 8 documented ones. Day 2 tightens this with RoundScore.
            expected = {
                "speaker_a_logic", "speaker_a_evidence", "speaker_a_persuasion",
                "speaker_b_logic", "speaker_b_evidence", "speaker_b_persuasion",
                "round_winner", "reasoning",
            }
            missing = expected - parsed.keys()
            if missing:
                logger.warning("judge JSON missing fields %s; storing raw", missing)
                return {"raw": raw, "parse_error": f"missing fields: {sorted(missing)}"}
            # Try full Pydantic validate for type/range safety.
            try:
                RoundScore.model_validate(parsed)
            except Exception as exc:
                logger.warning("RoundScore validation failed: %s", exc)
                return {"raw": raw, "parse_error": str(exc)}
            return parsed
        logger.warning("judge JSON was not an object; storing raw")
        return {"raw": raw, "parse_error": "not a JSON object"}
    except json.JSONDecodeError as exc:
        logger.warning("judge JSON decode failed: %s; storing raw", exc)
        return {"raw": raw, "parse_error": str(exc)}