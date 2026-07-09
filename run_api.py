"""Day 3 launcher: start the FastAPI server.

Mirrors `run_cli.py` at the repo root so the user has a one-liner
that's symmetric with the existing CLI.

Run with:
    python run_api.py
    python run_api.py --port 9000
    python run_api.py --reload
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make `src/` importable without `pip install -e .`.
sys.path.insert(0, str(Path(__file__).parent / "src"))

from debate_gpt.__main__ import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
