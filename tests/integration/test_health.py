"""Integration tests: /health endpoint contract.

PRD §11.4 / observability/health.py: the endpoint pings Redis and
Postgres in parallel and returns 200 only if both pass, 503 if
either is degraded. The body shape is:
  {
    "status": "ok" | "degraded",
    "redis": {"status": "ok"|"down", "latency_ms": float, "error"?: str},
    "postgres": {...}
  }
"""
from __future__ import annotations

import httpx
import pytest
from httpx import ASGITransport

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# 200 — both deps healthy
# ---------------------------------------------------------------------------

async def test_health_returns_200_when_both_deps_ok(app):
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["redis"]["status"] == "ok"
    assert body["postgres"]["status"] == "ok"
    assert "latency_ms" in body["redis"]
    assert "latency_ms" in body["postgres"]


async def test_health_latency_is_a_number(app):
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/health")
    body = r.json()
    assert isinstance(body["redis"]["latency_ms"], (int, float))
    assert isinstance(body["postgres"]["latency_ms"], (int, float))


# ---------------------------------------------------------------------------
# 503 — degraded dependencies
# ---------------------------------------------------------------------------

async def test_health_returns_503_when_redis_ping_fails(app, monkeypatch):
    """Force `redis_stream.ping` to return False (non-PONG)."""
    monkeypatch.setattr("debate_gpt.redis_stream.ping", lambda: False)

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/health")

    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "degraded"
    assert body["redis"]["status"] == "down"
    assert body["postgres"]["status"] == "ok"


async def test_health_returns_503_when_redis_ping_raises(app, monkeypatch):
    """An exception during the redis ping is caught and surfaced
    as `down` with the error string. The endpoint must not 5xx."""
    def _raise():
        raise RuntimeError("connection refused")

    monkeypatch.setattr("debate_gpt.redis_stream.ping", _raise)

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/health")

    assert r.status_code == 503
    body = r.json()
    assert body["redis"]["status"] == "down"
    assert "connection refused" in body["redis"].get("error", "")


async def test_health_returns_503_when_db_ping_fails(app, monkeypatch):
    async def _down() -> bool:
        return False

    monkeypatch.setattr("debate_gpt.db.ping", _down)

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/health")

    assert r.status_code == 503
    body = r.json()
    assert body["postgres"]["status"] == "down"
    assert body["redis"]["status"] == "ok"


async def test_health_returns_503_when_db_ping_raises(app, monkeypatch):
    async def _raise() -> bool:
        raise RuntimeError("connection refused")

    monkeypatch.setattr("debate_gpt.db.ping", _raise)

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/health")

    assert r.status_code == 503
    body = r.json()
    assert body["postgres"]["status"] == "down"
    assert "connection refused" in body["postgres"].get("error", "")
