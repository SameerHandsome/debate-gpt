"""Async Postgres (Neon) data access.

Single asyncpg connection pool, lazy-initialized on first use. All
operations are 2-second-timeout so /health can't hang.

Exposed helpers:
- `ping()`           — used by /health
- `create_debate()`  — called by the API at /debate/start
- `complete_debate()` — called at the end of the background debate task
- `get_debate()`     — used by GET /debate/{id}/result
- `list_debates()`   — used by GET /debates
- `delete_debate()`  — used by DELETE /debate/{id} (CASCADE removes rounds)

All row-shaped returns are plain `dict` (we don't expose asyncpg Record
objects, which can't be JSON-serialized directly).

IMPORTANT — event loop boundaries:
The shared `_pool` (created via `_get_pool()`) is bound to whichever
event loop first triggers its creation — normally the main uvicorn loop.
FastAPI's `BackgroundTasks` runs plain sync callables in a worker
*thread*, and the `_sync` bridge functions below call `asyncio.run(...)`,
which spins up a brand-new event loop in that thread. asyncpg pools
cannot be reused across event loops — doing so causes cryptic errors
like "another operation is in progress" or "connection was closed in
the middle of operation". To avoid this, the `_sync` bridge functions
open their own standalone connection (not the shared pool) scoped to
their own one-shot loop.
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any

import asyncpg

_pool: asyncpg.Pool | None = None
_pool_lock = asyncio.Lock()

DEFAULT_TIMEOUT = 8.0
MIN_POOL = 1
MAX_POOL = 5


async def _get_pool() -> asyncpg.Pool:
    """Lazy-init the global pool. asyncio.Lock guards first access.

    Only ever call this from the main event loop (i.e. from `async def`
    route handlers). Background-thread code must use the standalone
    connection helpers below instead.
    """
    global _pool
    if _pool is not None:
        return _pool
    async with _pool_lock:
        if _pool is None:
            dsn = os.environ.get("DATABASE_URL", "")
            if not dsn:
                raise RuntimeError("DATABASE_URL is not set")
            _pool = await asyncpg.create_pool(
                dsn=dsn,
                min_size=MIN_POOL,
                max_size=MAX_POOL,
                timeout=DEFAULT_TIMEOUT,
            )
    return _pool


async def close_pool() -> None:
    """Close the pool on app shutdown. Safe to call multiple times."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def _dsn() -> str:
    dsn = os.environ.get("DATABASE_URL", "")
    if not dsn:
        raise RuntimeError("DATABASE_URL is not set")
    return dsn


async def ping() -> bool:
    """Return True iff a SELECT 1 round-trip succeeds within DEFAULT_TIMEOUT."""
    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            await asyncio.wait_for(conn.execute("SELECT 1"), timeout=DEFAULT_TIMEOUT)
        return True
    except Exception:
        return False


# ---------- Row-shaped helpers ----------

def _row_to_dict(row: asyncpg.Record | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


# ---------- CRUD (main event loop only — uses the shared pool) ----------

async def create_debate(
    topic: str,
    position_pro: str,
    position_con: str,
    debate_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Insert a `debates` row; return its id.

    If `debate_id` is supplied, the row is inserted with that exact UUID
    (the API uses this so the response `session_id` matches the row id).
    """
    pool = await _get_pool()
    async with pool.acquire() as conn:
        if debate_id is not None:
            return await conn.fetchval(
                "INSERT INTO debates (id, topic, position_pro, position_con) "
                "VALUES ($1, $2, $3, $4) RETURNING id",
                debate_id, topic, position_pro, position_con,
            )
        return await conn.fetchval(
            "INSERT INTO debates (topic, position_pro, position_con) "
            "VALUES ($1, $2, $3) RETURNING id",
            topic, position_pro, position_con,
        )


async def complete_debate(
    debate_id: uuid.UUID, winner: str, rounds: list[dict[str, Any]]
) -> None:
    """Mark the debate complete and insert one debate_rounds row per round.

    `rounds` items: {"round_number": int, "pro": str, "con": str,
                     "score": dict, "winner": str}.
    """
    pool = await _get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE debates "
                "SET status = 'complete', winner = $1, completed_at = NOW() "
                "WHERE id = $2",
                winner, debate_id,
            )
            for r in rounds:
                await conn.execute(
                    "INSERT INTO debate_rounds "
                    "(debate_id, round_number, pro_argument, con_argument, "
                    " judge_scores, round_winner) "
                    "VALUES ($1, $2, $3, $4, $5::jsonb, $6)",
                    debate_id,
                    int(r["round_number"]),
                    r["pro"],
                    r["con"],
                    json.dumps(r["score"]),
                    r["winner"],
                )


async def fail_debate(debate_id: uuid.UUID) -> None:
    """Mark the debate as errored. Used by the runtime's except handlers."""
    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE debates SET status = 'error', completed_at = NOW() "
                "WHERE id = $1",
                debate_id,
            )
    except Exception:
        # If we can't even reach the DB, the operator will see the
        # /health endpoint fail. Don't re-raise from a cleanup path.
        pass


async def get_debate(debate_id: uuid.UUID) -> dict[str, Any] | None:
    """Return `{debate: {...}, rounds: [{...}, ...]}` or None if not found.

    The frontend GET /debate/{id}/result endpoint serializes this directly.
    """
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, topic, position_pro, position_con, status, winner, "
            "created_at, completed_at FROM debates WHERE id = $1",
            debate_id,
        )
        if row is None:
            return None
        round_rows = await conn.fetch(
            "SELECT id, round_number, pro_argument, con_argument, "
            "judge_scores, round_winner, created_at "
            "FROM debate_rounds WHERE debate_id = $1 "
            "ORDER BY round_number ASC",
            debate_id,
        )
        rounds = []
        for rr in round_rows:
            d = _row_to_dict(rr)
            # asyncpg returns JSONB as a Python dict already when the
            # connection codec is default, but be defensive:
            if isinstance(d.get("judge_scores"), str):
                d["judge_scores"] = json.loads(d["judge_scores"])
            rounds.append(d)
        return {"debate": _row_to_dict(row), "rounds": rounds}


async def list_debates(page: int = 1, page_size: int = 20) -> dict[str, Any]:
    """Paginated summary list. Page is 1-indexed. Total count included."""
    page = max(1, int(page))
    page_size = max(1, min(100, int(page_size)))
    offset = (page - 1) * page_size

    pool = await _get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM debates")
        rows = await conn.fetch(
            "SELECT id, topic, status, winner, created_at, completed_at "
            "FROM debates ORDER BY created_at DESC "
            "LIMIT $1 OFFSET $2",
            page_size, offset,
        )
    return {
        "page": page,
        "page_size": page_size,
        "total": int(total or 0),
        "items": [_row_to_dict(r) for r in rows],
    }


async def delete_debate(debate_id: uuid.UUID) -> bool:
    """Delete the debate row. Returns True if a row was removed.

    `ON DELETE CASCADE` removes the rows in `debate_rounds` atomically
    (PRD §6).
    """
    pool = await _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM debates WHERE id = $1", debate_id
        )
    # asyncpg returns 'DELETE N' — parse the rowcount.
    try:
        return int(result.split()[-1]) > 0
    except (ValueError, IndexError):
        return False


# ---------- Sync bridge (for the BackgroundTasks thread) ----------
#
# These do NOT use the shared `_pool` — that object belongs to the main
# event loop. Each call here opens its own standalone asyncpg connection
# scoped to the one-shot loop that `asyncio.run()` creates, and closes it
# when done. This avoids the cross-event-loop asyncpg errors.

async def _create_debate_standalone(
    topic: str,
    position_pro: str,
    position_con: str,
    debate_id: uuid.UUID | None,
) -> uuid.UUID:
    conn = await asyncpg.connect(dsn=_dsn(), timeout=DEFAULT_TIMEOUT)
    try:
        if debate_id is not None:
            return await conn.fetchval(
                "INSERT INTO debates (id, topic, position_pro, position_con) "
                "VALUES ($1, $2, $3, $4) RETURNING id",
                debate_id, topic, position_pro, position_con,
            )
        return await conn.fetchval(
            "INSERT INTO debates (topic, position_pro, position_con) "
            "VALUES ($1, $2, $3) RETURNING id",
            topic, position_pro, position_con,
        )
    finally:
        await conn.close()


async def _complete_debate_standalone(
    debate_id: uuid.UUID, winner: str, rounds: list[dict[str, Any]]
) -> None:
    conn = await asyncpg.connect(dsn=_dsn(), timeout=DEFAULT_TIMEOUT)
    try:
        async with conn.transaction():
            await conn.execute(
                "UPDATE debates "
                "SET status = 'complete', winner = $1, completed_at = NOW() "
                "WHERE id = $2",
                winner, debate_id,
            )
            for r in rounds:
                await conn.execute(
                    "INSERT INTO debate_rounds "
                    "(debate_id, round_number, pro_argument, con_argument, "
                    " judge_scores, round_winner) "
                    "VALUES ($1, $2, $3, $4, $5::jsonb, $6)",
                    debate_id,
                    int(r["round_number"]),
                    r["pro"],
                    r["con"],
                    json.dumps(r["score"]),
                    r["winner"],
                )
    finally:
        await conn.close()


async def _fail_debate_standalone(debate_id: uuid.UUID) -> None:
    try:
        conn = await asyncpg.connect(dsn=_dsn(), timeout=DEFAULT_TIMEOUT)
        try:
            await conn.execute(
                "UPDATE debates SET status = 'error', completed_at = NOW() "
                "WHERE id = $1",
                debate_id,
            )
        finally:
            await conn.close()
    except Exception:
        pass


def complete_debate_sync(
    debate_id: uuid.UUID, winner: str, rounds: list[dict[str, Any]]
) -> None:
    """Drive completion from a sync context (the BackgroundTasks thread).

    Spins up a one-shot event loop with its own standalone DB connection
    — never touches the shared pool created on the main loop.
    """
    asyncio.run(_complete_debate_standalone(debate_id, winner, rounds))


def create_debate_sync(
    topic: str,
    position_pro: str,
    position_con: str,
    debate_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Drive creation from a sync context (the runtime thread)."""
    return asyncio.run(
        _create_debate_standalone(topic, position_pro, position_con, debate_id)
    )


def fail_debate_sync(debate_id: uuid.UUID) -> None:
    asyncio.run(_fail_debate_standalone(debate_id))


__all__ = [
    "ping",
    "close_pool",
    "create_debate",
    "complete_debate",
    "fail_debate",
    "get_debate",
    "list_debates",
    "delete_debate",
    "create_debate_sync",
    "complete_debate_sync",
    "fail_debate_sync",
]