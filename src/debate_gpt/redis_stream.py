"""Sync Upstash Redis REST client.

Upstash's REST API supports Redis Stream commands (`XADD`, `XRANGE`,
`XLEN`, `DEL`) over plain HTTPS POSTs. We use `httpx.Client` once per
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
`xrange(stream, since_id="(<id>")` returns entries strictly greater than
the given id; `-` is the start of the stream.
"""
from __future__ import annotations

import json
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


def _post(command_path: str) -> dict[str, Any]:
    r = _get_client().post(
        f"{_url()}/{command_path}",
        headers=_auth_headers(),
        timeout=_TIMEOUT_SECONDS,
    )
    r.raise_for_status()
    return r.json()


# ---------- Public API ----------

def xadd(session_id: str, fields: dict[str, str]) -> str:
    """Append one entry to the session stream; return the new entry id.

    Upstash XADD payload: an array of `{id, fields}` objects; `id: "*"`
    tells the server to generate one.
    """
    body = [{"id": "*", "fields": {k: str(v) for k, v in fields.items()}}]
    r = _get_client().post(
        f"{_url()}/xadd/{_stream_prefix}{session_id}",
        headers=_auth_headers(),
        json=body,
        timeout=_TIMEOUT_SECONDS,
    )
    r.raise_for_status()
    return r.json()["result"]


def xrange(session_id: str, since_id: str = "-") -> list[dict[str, Any]]:
    """Return entries with id > `since_id`.

    Each entry is a dict: `{"id": "1700…-0", "fields": {"event": …, ...}}`.
    Empty list if the stream doesn't exist or no new entries.
    """
    r = _get_client().post(
        f"{_url()}/xrange/{_stream_prefix}{session_id}/{since_id}",
        headers=_auth_headers(),
        timeout=_TIMEOUT_SECONDS,
    )
    r.raise_for_status()
    raw = r.json().get("result") or []
    return [{"id": entry[0], "fields": entry[1]} for entry in raw]


def xlen(session_id: str) -> int:
    """Return the number of entries in the stream (0 if absent)."""
    r = _get_client().post(
        f"{_url()}/xlen/{_stream_prefix}{session_id}",
        headers=_auth_headers(),
        timeout=_TIMEOUT_SECONDS,
    )
    r.raise_for_status()
    return r.json().get("result") or 0


def delete_key(session_id: str) -> None:
    """Delete the stream key. Idempotent — no error if missing."""
    r = _get_client().post(
        f"{_url()}/del/{_stream_prefix}{session_id}",
        headers=_auth_headers(),
        timeout=_TIMEOUT_SECONDS,
    )
    r.raise_for_status()


def ping() -> bool:
    """PING the server. Returns True on `+PONG`, False on any error.

    Used by the /health endpoint.
    """
    try:
        r = _get_client().post(
            f"{_url()}/ping",
            headers=_auth_headers(),
            timeout=_TIMEOUT_SECONDS,
        )
        r.raise_for_status()
        return r.json().get("result") == "PONG"
    except Exception:
        return False


__all__ = [
    "xadd",
    "xrange",
    "xlen",
    "delete_key",
    "ping",
]
