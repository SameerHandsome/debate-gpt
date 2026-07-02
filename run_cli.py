"""Day 2 CLI runner: argparse-driven topic, end-to-end debate, transcript printout.

Run with:
    python run_cli.py
    python run_cli.py --topic "Social media platforms should be regulated as public utilities"
    python run_cli.py --rounds 5

Requires a populated .env at the repo root (see .env.example).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import uuid
from pathlib import Path

# Make `src/` importable without installing the package.
sys.path.insert(0, str(Path(__file__).parent / "src"))

# Reopen stdout in UTF-8 so the Windows cp1252 default doesn't crash on
# non-ASCII characters in the LLM output (Day 2: surfaced by debate 2).
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from debate_gpt.config import load_settings  # noqa: E402
from debate_gpt.graph import build_graph  # noqa: E402
from debate_gpt.state import DebateState  # noqa: E402

DEFAULT_TOPIC = "Universal basic income should be adopted worldwide"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a Debate-GPT debate end-to-end and print the transcript."
    )
    parser.add_argument(
        "--topic",
        default=DEFAULT_TOPIC,
        help=f"Debate motion (default: {DEFAULT_TOPIC!r})",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=None,
        help="Override MAX_ROUNDS from .env (default: settings['max_rounds'])",
    )
    return parser.parse_args()


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

    args = parse_args()
    max_rounds = args.rounds if args.rounds is not None else settings["max_rounds"]

    initial: DebateState = {
        "session_id": str(uuid.uuid4()),
        "topic": args.topic,
        "position_pro": f"For: {args.topic}",
        "position_con": f"Against: {args.topic}",
        "round": 1,
        "max_rounds": max_rounds,
        "messages": [],
        "round_scores": [],
        "winner": None,
        "trace_id": None,
    }

    print(f"\nDebate-GPT — Day 2 CLI")
    print(f"Topic:  {args.topic}")
    print(f"Rounds: {max_rounds}")
    print(f"Session: {initial['session_id']}")
    print("=" * 60)

    started = time.perf_counter()
    graph = build_graph()
    final = graph.invoke(initial)
    elapsed = time.perf_counter() - started

    print_results(final)
    print_round_summary(final)
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


def print_round_summary(final: DebateState) -> None:
    """Print a one-line per-round summary and warn on any parse fallback."""
    round_scores = list(final.get("round_scores") or [])
    for i, score in enumerate(round_scores, start=1):
        if "parse_error" in score:
            print(
                f"\nWARNING: round {i} judge output failed to parse after "
                f"retries: {score.get('parse_error')}",
                file=sys.stderr,
            )
            continue
        pro = score.get("pro_score", "?")
        con = score.get("con_score", "?")
        winner = score.get("round_winner", "?")
        print(f"\nRound {i} summary: pro={pro} con={con} winner={winner}")


if __name__ == "__main__":
    raise SystemExit(main())
