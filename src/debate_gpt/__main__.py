"""`python -m debate_gpt api` — launch the FastAPI server.

Default host/port: 0.0.0.0:8000. Override with `--host` / `--port`.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make `src/` importable so `python -m debate_gpt` works without `pip
# install -e .`. Mirrors the pattern in `dry_run.py` and `run_cli.py`.
_SRC = Path(__file__).resolve().parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import uvicorn  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Debate-GPT FastAPI server."
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true",
                        help="Auto-reload on code changes (dev only).")
    parser.add_argument("--log-level", default="info",
                        choices=["critical", "error", "warning",
                                 "info", "debug", "trace"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    uvicorn.run(
        "debate_gpt.api:create_app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
        factory=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
