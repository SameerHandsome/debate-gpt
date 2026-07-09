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

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage, HumanMessage
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from .config import load_settings
from .prompts import build_con_messages, build_judge_messages, build_pro_messages
from .schemas import RoundScore
from .state import DebateState
from .verdict import con_total_for_round, pro_total_for_round

logger = logging.getLogger(__name__)


# Signature of the streaming sink the runtime passes in. Receives the
# caller-supplied event name (e.g. "pro_token"), the round number, and the
# newly-flushed content chunk. Called from inside a sync thread; must not
# raise. Used by Day 3 SSE.
ChunkSink = Callable[[str, int, str], None]


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

# How many characters of streaming buffer to flush per chunk. Smaller =
# more events; larger = fewer round-trips. ~50 chars is a good balance
# for human-readable token flow.
_CHUNK_FLUSH_CHARS = 50


def _stream_and_collect(
    llm,
    messages: list,
    event_name: str,
    round_no: int,
    chunk_sink: ChunkSink | None,
) -> str:
    """Run `llm.stream(messages)`; flush incremental chunks to `chunk_sink`
    and return the joined final content.

    Each flush sends the *new* text accumulated since the last flush
    (e.g. ~50 chars at a time). The sink is called with
    (event_name, round_no, content). Final-flush is always called so the
    last partial buffer is never lost.

    If `chunk_sink` is None (e.g. dry-run, pytest), no flushes happen —
    the function still returns the full content for state accumulation.
    """
    full: list[str] = []
    pending: list[str] = []  # unflushed accumulator
    pending_len = 0
    for chunk in llm.stream(messages):
        text = _extract_content(chunk) if chunk is not None else ""
        if not text:
            continue
        full.append(text)
        if chunk_sink is not None:
            pending.append(text)
            pending_len += len(text)
            if pending_len >= _CHUNK_FLUSH_CHARS:
                chunk_sink(event_name, round_no, "".join(pending))
                pending = []
                pending_len = 0

    final = "".join(full)
    if chunk_sink is not None and pending:
        # Final flush so nothing is dropped.
        chunk_sink(event_name, round_no, "".join(pending))
    return final


def make_pro_node(llm, chunk_sink: ChunkSink | None = None) -> NodeFn:
    def pro_node(state: DebateState) -> dict:
        messages = build_pro_messages(state)
        # Use the streaming path only when a sink is attached; otherwise
        # call invoke() so dry-run / pytests don't pay the streaming cost.
        if chunk_sink is None:
            response = llm.invoke(messages)
            content = _extract_content(response)
        else:
            content = _stream_and_collect(
                llm, messages, "pro_token", state["round"], chunk_sink
            )
        logger.info("pro round=%d chars=%d", state["round"], len(content))
        return {"messages": [AIMessage(content=content, name="Pro")]}

    return pro_node


def make_con_node(llm, chunk_sink: ChunkSink | None = None) -> NodeFn:
    def con_node(state: DebateState) -> dict:
        messages = build_con_messages(state)
        if chunk_sink is None:
            response = llm.invoke(messages)
            content = _extract_content(response)
        else:
            content = _stream_and_collect(
                llm, messages, "con_token", state["round"], chunk_sink
            )
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
        bundle = build_judge_messages(state, pro_text, con_text, swap=swap)
        score_dict = _invoke_judge_with_retry(llm, bundle.messages, max_retries=2)

        # On a successful parse, translate the Speaker A/B verdict back to
        # pro/con and compute the derived totals for the verdict node (Day 3).
        if "round_winner" in score_dict and "parse_error" not in score_dict:
            score_dict["round_winner"] = _translate_winner(
                score_dict["round_winner"], swap
            )
            score_dict["pro_score"] = pro_total_for_round(score_dict, swap)
            score_dict["con_score"] = con_total_for_round(score_dict, swap)

        next_round = state["round"] + 1
        logger.info(
            "judge round=%d swap=%s winner=%s pro=%s con=%s next_round=%d",
            state["round"],
            swap,
            score_dict.get("round_winner"),
            score_dict.get("pro_score"),
            score_dict.get("con_score"),
            next_round,
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
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
_STRUCTURED_UNSUPPORTED = (NotImplementedError, AttributeError, ValueError)

# Concise feedback injected on retry. The model sees its own mistake and
# a terse instruction to return ONLY the JSON object.
_RETRY_FEEDBACK_TMPL = (
    "Your previous output failed validation: {err}\n"
    "Return ONLY the JSON object exactly matching the schema above. "
    "No markdown fences, no commentary, no trailing prose."
)


def _invoke_judge_with_retry(llm, messages: list, max_retries: int = 2) -> dict:
    """Invoke the judge and return a RoundScore dict.

    Strategy:
      1) Try `llm.with_structured_output(RoundScore)` once (tool-calling path).
         If the provider doesn't support it, or the model emits malformed
         tool args, fall through to path 2.
      2) Manual parse: invoke plain LLM, extract the first {...} blob,
         validate with RoundScore. On any failure, append a feedback
         HumanMessage and re-invoke, up to `max_retries` additional times.

    Always returns a dict. On full failure, returns
    `{"raw": ..., "parse_error": "..."}` so the graph keeps running.
    """
    # --- Path 1: structured output (tool calling) ---
    try:
        structured = llm.with_structured_output(RoundScore)
        result = structured.invoke(messages)
        if isinstance(result, RoundScore):
            return result.model_dump()
        # Some adapters return a dict already.
        return RoundScore.model_validate(result).model_dump()
    except _STRUCTURED_UNSUPPORTED as exc:
        logger.info(
            "structured_output unsupported (%s); falling back to manual parse", exc
        )
    except (ValidationError, OutputParserException, json.JSONDecodeError) as exc:
        logger.warning(
            "structured_output validation failed: %s; falling back to manual parse",
            exc,
        )

    # --- Path 2: manual parse with retry ---
    convo = list(messages)  # copy; we may append feedback
    last_err: str | None = None
    last_raw: str | None = None
    for attempt in range(max_retries + 1):  # initial + max_retries retries
        response = llm.invoke(convo)
        raw = _extract_content(response)
        last_raw = raw
        try:
            return _parse_judge_output_strict(raw)
        except (ValidationError, ValueError, json.JSONDecodeError) as exc:
            last_err = str(exc)
            logger.warning(
                "judge parse attempt %d/%d failed: %s",
                attempt + 1,
                max_retries + 1,
                exc,
            )
            if attempt < max_retries:
                convo = convo + [
                    HumanMessage(content=_RETRY_FEEDBACK_TMPL.format(err=last_err))
                ]

    return {"raw": last_raw or "", "parse_error": last_err or "unknown parse failure"}


def _parse_judge_output_strict(raw: str) -> dict:
    """Strict parse: extract the first JSON object, validate with RoundScore.

    Raises on failure (the retry helper owns the fallback decision).
    """
    text = _JSON_FENCE.sub("", raw.strip()).strip()
    match = _JSON_OBJECT_RE.search(text)
    if not match:
        raise ValueError("no JSON object found in judge output")
    parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("judge JSON is not an object")
    return RoundScore.model_validate(parsed).model_dump()


def _translate_winner(winner: str, swap: bool) -> str:
    """Translate Speaker A/B verdict back to pro/con/tie.

    swap=True (even rounds): Con was Speaker A, Pro was Speaker B.
    swap=False (odd rounds): Pro was Speaker A, Con was Speaker B.
    """
    if winner == "tie":
        return "tie"
    if swap:
        # Con = A, Pro = B
        return "con" if winner == "A" else "pro"
    # Pro = A, Con = B
    return "pro" if winner == "A" else "con"
