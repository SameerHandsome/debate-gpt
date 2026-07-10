"""Sync Upstash Redis REST client.

Upstash's REST API accepts a whole Redis command as a single JSON array
posted to the base URL: ["XADD", "mykey", "*", "field1", "value1", ...].
The first element is the command name, and the rest are its arguments
in the same order as the Redis protocol. We use `httpx.Client` once per
process and re-use it across calls.

Used by:
- `runtime.py` (Day 3 background task) — `xadd` from a sync thread.
- `api.py` SSE handler — `xrange` via `asyncio.to_thread`.

Key shape: `debate:stream:{session_id}`

XADD fields (per PRD §5.2):
    {
        "event":   "pro_token" | "con_token" | "judge_score" | "verdict",
        "round":   "1",          # 0 for verdict
        "content": "<chunk text>"   # JSON string for judge_score / verdict
    }

Upstash returns stream entry ids of the form `<ms-timestamp>-<seq>`.
XRANGE requires both a start and end id; "-" is the start of the stream
and "+" is the end. An exclusive start like "(<id>" returns only entries
strictly greater than that id (Redis 6.2+ syntax).
"""
from __future__ import annotations

import os
import threading
from typing import Any

import httpx


_STREAM_PREFIX = "debate:stream:"
_TIMEOUT_SECONDS = 2.0

_client: httpx.Client | None = None
_client_lock = threading.Lock()


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = httpx.Client(timeout=_TIMEOUT_SECONDS)
    return _client


def _url() -> str:
    base = os.environ.get("UPSTASH_REDIS_REST_URL", "").rstrip("/")
    if not base:
        raise RuntimeError("UPSTASH_REDIS_REST_URL is not set")
    return base


def _auth_headers() -> dict[str, str]:
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
    if not token:
        raise RuntimeError("UPSTASH_REDIS_REST_TOKEN is not set")
    return {"Authorization": f"Bearer {token}"}


def _command(*parts: Any) -> Any:
    """Send a single Redis command as a JSON array to the base REST URL.

    Returns the parsed JSON response, e.g. {"result": ...} or {"error": ...}.
    """
    r = _get_client().post(
        _url(),
        headers=_auth_headers(),
        json=list(parts),
        timeout=_TIMEOUT_SECONDS,
    )
    r.raise_for_status()
    return r.json()


# ---------- Public API ----------

def xadd(session_id: str, fields: dict[str, str]) -> str:
    """Append one entry to the session stream; return the new entry id."""
    key = f"{_STREAM_PREFIX}{session_id}"
    args: list[Any] = ["XADD", key, "*"]
    for k, v in fields.items():
        args.append(k)
        args.append(str(v))
    result = _command(*args)
    return result["result"]


def xrange(session_id: str, since_id: str = "-") -> list[dict[str, Any]]:
    """Return entries with id > `since_id`, up to the end of the stream.

    Each entry is a dict: `{"id": "1700…-0", "fields": {"event": …, ...}}`.
    Empty list if the stream doesn't exist or no new entries.
    """
    key = f"{_STREAM_PREFIX}{session_id}"
    result = _command("XRANGE", key, since_id, "+")
    raw = result.get("result") or []
    entries: list[dict[str, Any]] = []
    for entry in raw:
        entry_id = entry[0]
        flat_fields = entry[1]  # [field1, value1, field2, value2, ...]
        fields = dict(zip(flat_fields[0::2], flat_fields[1::2]))
        entries.append({"id": entry_id, "fields": fields})
    return entries


def xlen(session_id: str) -> int:
    """Return the number of entries in the stream (0 if absent)."""
    key = f"{_STREAM_PREFIX}{session_id}"
    result = _command("XLEN", key)
    return result.get("result") or 0


def delete_key(session_id: str) -> None:
    """Delete the stream key. Idempotent — no error if missing."""
    key = f"{_STREAM_PREFIX}{session_id}"
    _command("DEL", key)


def ping() -> bool:
    """PING the server. Returns True on `PONG`, False on any error.

    Used by the /health endpoint.
    """
    try:
        result = _command("PING")
        return result.get("result") == "PONG"
    except Exception:
        return False


__all__ = [
    "xadd",
    "xrange",
    "xlen",
    "delete_key",
    "ping",
]