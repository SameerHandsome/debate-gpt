"""Day 1 CLI runner: hardcoded topic, end-to-end debate, transcript printout.

Run with:
    python run_cli.py

Requires a populated .env at the repo root (see .env.example).
"""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from pathlib import Path

# Make `src/` importable without installing the package.
sys.path.insert(0, str(Path(__file__).parent / "src"))

from debate_gpt.config import load_settings  # noqa: E402
from debate_gpt.graph import build_graph  # noqa: E402
from debate_gpt.state import DebateState  # noqa: E402

TOPIC = "Universal basic income should be adopted worldwide"


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    try:
        settings = load_settings()
    except EnvironmentError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    initial: DebateState = {
        "session_id": str(uuid.uuid4()),
        "topic": TOPIC,
        "position_pro": f"For: {TOPIC}",
        "position_con": f"Against: {TOPIC}",
        "round": 1,
        "max_rounds": settings["max_rounds"],
        "messages": [],
        "round_scores": [],
        "winner": None,
        "trace_id": None,
    }

    print(f"\nDebate-GPT — Day 1 CLI")
    print(f"Topic:  {TOPIC}")
    print(f"Rounds: {settings['max_rounds']}")
    print(f"Session: {initial['session_id']}")
    print("=" * 60)

    started = time.perf_counter()
    graph = build_graph()
    final = graph.invoke(initial)
    elapsed = time.perf_counter() - started

    print_results(final)
    print("=" * 60)
    print(f"Done. Elapsed: {elapsed:.1f}s")
    return 0


def print_results(final: DebateState) -> None:
    """Print the debate transcript + scorecards, grouped by round."""
    messages = list(final.get("messages") or [])
    round_scores = list(final.get("round_scores") or [])

    # Iterate ordered; Pro opens a new round, Con closes it.
    ordered = [m for m in messages if getattr(m, "name", None) in ("Pro", "Con")]
    grouped: dict[int, dict[str, str]] = {}
    current_round = 1
    for msg in ordered:
        grouped.setdefault(current_round, {})
        grouped[current_round][getattr(msg, "name")] = msg.content
        if getattr(msg, "name") == "Con":
            current_round += 1

    for round_no in sorted(grouped.keys()):
        block = grouped[round_no]
        print(f"\n=== Round {round_no} — Pro ===")
        print(block.get("Pro", "<missing>"))
        print(f"\n=== Round {round_no} — Con ===")
        print(block.get("Con", "<missing>"))
        score = round_scores[round_no - 1] if round_no - 1 < len(round_scores) else None
        print(f"\n=== Round {round_no} — Judge ===")
        if score is None:
            print("<no score>")
        else:
            print(json.dumps(score, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())