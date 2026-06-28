"""Environment loading and settings.

Reads GROQ_API_KEY, OPENROUTER_API_KEY, and MAX_ROUNDS from the process
environment (typically populated by a local .env file). Fails fast with a
clear, actionable error if a required key is missing.
"""

from __future__ import annotations

import os
from typing import TypedDict

from dotenv import load_dotenv


class Settings(TypedDict):
    groq_api_key: str
    openrouter_api_key: str
    max_rounds: int


_REQUIRED_KEYS = ("GROQ_API_KEY", "OPENROUTER_API_KEY")


def load_settings() -> Settings:
    """Load settings from .env + process env. Raises EnvironmentError if a
    required API key is missing."""
    load_dotenv()

    missing = [k for k in _REQUIRED_KEYS if not os.getenv(k)]
    if missing:
        bullets = "\n".join(f"  - {k}" for k in missing)
        raise EnvironmentError(
            "Missing required environment variable(s):\n"
            f"{bullets}\n\n"
            "Copy .env.example to .env at the repo root and fill in your keys:\n"
            "  cp .env.example .env   # then edit .env\n"
        )

    raw_max = os.getenv("MAX_ROUNDS", "3")
    try:
        max_rounds = int(raw_max)
    except ValueError as exc:
        raise EnvironmentError(f"MAX_ROUNDS must be an integer, got {raw_max!r}") from exc
    if not 2 <= max_rounds <= 5:
        raise EnvironmentError(f"MAX_ROUNDS must be between 2 and 5, got {max_rounds}")

    return Settings(
        groq_api_key=os.environ["GROQ_API_KEY"],
        openrouter_api_key=os.environ["OPENROUTER_API_KEY"],
        max_rounds=max_rounds,
    )