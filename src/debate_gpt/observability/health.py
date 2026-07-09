"""`/health` route + per-dependency ping helpers.

Per PRD §11.4:
- Pings Upstash Redis via REST.
- Runs SELECT 1 against Neon via the asyncpg pool.
- 2-second timeout each.
- Returns 200 only if both pass, 503 if either is degraded.
- Body shape: `{status, redis: {...}, postgres: {...}}` with per-dep
  status, latency_ms, and (on failure) error string.
"""
from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .. import db, redis_stream

router = APIRouter()


async def check_redis() -> dict:
    t = time.perf_counter()
    try:
        ok = await asyncio.to_thread(redis_stream.ping)
        latency_ms = (time.perf_counter() - t) * 1000
        if ok:
            return {"status": "ok", "latency_ms": round(latency_ms, 1)}
        return {"status": "down", "latency_ms": round(latency_ms, 1),
                "error": "ping returned non-PONG"}
    except Exception as exc:  # noqa: BLE001
        latency_ms = (time.perf_counter() - t) * 1000
        return {"status": "down", "latency_ms": round(latency_ms, 1),
                "error": str(exc)}


async def check_postgres() -> dict:
    t = time.perf_counter()
    try:
        ok = await db.ping()
        latency_ms = (time.perf_counter() - t) * 1000
        if ok:
            return {"status": "ok", "latency_ms": round(latency_ms, 1)}
        return {"status": "down", "latency_ms": round(latency_ms, 1),
                "error": "SELECT 1 failed"}
    except Exception as exc:  # noqa: BLE001
        latency_ms = (time.perf_counter() - t) * 1000
        return {"status": "down", "latency_ms": round(latency_ms, 1),
                "error": str(exc)}


@router.get("/health")
async def health() -> JSONResponse:
    redis_s, pg_s = await asyncio.gather(check_redis(), check_postgres())
    overall = "ok" if redis_s["status"] == "ok" and pg_s["status"] == "ok" else "degraded"
    return JSONResponse(
        status_code=200 if overall == "ok" else 503,
        content={"status": overall, "redis": redis_s, "postgres": pg_s},
    )


__all__ = ["router", "check_redis", "check_postgres"]
